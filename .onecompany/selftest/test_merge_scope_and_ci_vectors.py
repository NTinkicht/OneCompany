"""OC-P0-06 vectors: off-scope diff and failed-CI merge refusal (#336).

``scope_guard.scope_errors`` and ``required_checks.evaluate_required_checks`` are
the two offline gates ``scripts/merge.py`` and ``scripts/gate.py`` consult before
any merge mutation. These vectors pin that each refuses (fails closed) instead of
admitting an off-scope change or a non-green required check.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import required_checks  # noqa: E402
from scope_guard import scope_covers_path, scope_errors, undeclared_paths  # noqa: E402

SHA = "c" * 40
WORKFLOW_PATH = ".github/workflows/onecompany-validate.yml"


class OffScopeDiffVectors(unittest.TestCase):
    def test_unresolved_work_unit_refuses(self):
        for work_unit in (None, [], "WU-1", 7):
            with self.subTest(work_unit=work_unit):
                errors = scope_errors(["scripts/a.py"], work_unit)  # type: ignore[arg-type]
                self.assertEqual(
                    errors, ["work unit could not be resolved for live PR scope verification"]
                )

    def test_missing_empty_or_non_list_write_scope_refuses(self):
        for work_unit in (
            {},
            {"write_scope": []},
            {"write_scope": None},
            {"write_scope": "scripts/**"},
            {"write_scope": {"scripts/**": True}},
        ):
            with self.subTest(work_unit=work_unit):
                errors = scope_errors(["scripts/a.py"], work_unit)
                self.assertEqual(len(errors), 1)
                self.assertIn("no declared write_scope", errors[0])

    def test_blank_only_scope_entries_cover_nothing(self):
        errors = scope_errors(["scripts/a.py"], {"write_scope": ["", "   "]})
        self.assertEqual(
            errors, ["live PR modifies paths outside declared write_scope: scripts/a.py"]
        )

    def test_off_scope_paths_are_named_sorted_and_deduplicated(self):
        errors = scope_errors(
            ["scripts/a.py", "docs/x.md", ".github/workflows/ci.yml", "docs/x.md"],
            {"write_scope": ["scripts/**"]},
        )
        self.assertEqual(
            errors,
            [
                "live PR modifies paths outside declared write_scope: "
                ".github/workflows/ci.yml, docs/x.md"
            ],
        )

    def test_in_scope_diff_is_admitted(self):
        self.assertEqual(
            scope_errors(
                ["scripts/a.py", ".onecompany/selftest/test_a.py"],
                {"write_scope": ["scripts/a.py", ".onecompany/selftest/**"]},
            ),
            [],
        )

    def test_dotfile_directory_is_not_aliased_to_plain_name(self):
        # Regression: lstrip("./") turned ".github" into "github".
        for scope, path in (
            ("github/**", ".github/workflows/ci.yml"),
            ("github", ".github/workflows/ci.yml"),
            ("onecompany/config.json", ".onecompany/config.json"),
            (".github/**", "github/workflows/ci.yml"),
            ("selftest/**", "..selftest/x.py"),
        ):
            with self.subTest(scope=scope, path=path):
                self.assertFalse(scope_covers_path(scope, path))
        errors = scope_errors([".github/workflows/ci.yml"], {"write_scope": ["github/**"]})
        self.assertEqual(
            errors,
            ["live PR modifies paths outside declared write_scope: .github/workflows/ci.yml"],
        )

    def test_dotfile_scope_still_covers_its_own_paths(self):
        self.assertTrue(scope_covers_path(".github/workflows/validate.yml", ".github/workflows/validate.yml"))
        self.assertTrue(scope_covers_path(".onecompany/selftest", ".onecompany/selftest/test_x.py"))
        self.assertTrue(scope_covers_path("./scripts", "scripts/a.py"))
        self.assertTrue(scope_covers_path("/scripts/", "scripts/a.py"))

    def test_traversal_and_malformed_paths_fail_closed(self):
        for path in (
            "scripts/../.github/workflows/ci.yml",
            "scripts/./a.py",
            "scripts//a.py",
            "..",
            "../outside.py",
            "scripts/a.py\x00.md",
            "",
            "   ",
            "/",
        ):
            with self.subTest(path=path):
                self.assertFalse(scope_covers_path("scripts/**", path))
                self.assertFalse(scope_covers_path("**", path))
        self.assertEqual(
            undeclared_paths(["scripts/../.github/workflows/ci.yml"], ["scripts/**"]),
            ["scripts/../.github/workflows/ci.yml"],
        )

    def test_traversal_in_declared_scope_covers_nothing(self):
        for scope in ("scripts/../.github/**", "../**", "scripts/./**"):
            with self.subTest(scope=scope):
                self.assertFalse(scope_covers_path(scope, ".github/workflows/ci.yml"))
                self.assertFalse(scope_covers_path(scope, "scripts/a.py"))


def _check(check_id: int, status: str, conclusion: str | None, run_id: int) -> dict:
    return {
        "id": check_id,
        "name": "validate",
        "head_sha": SHA,
        "status": status,
        "conclusion": conclusion,
        "details_url": f"https://github.com/owner/repo/actions/runs/{run_id}/job/{check_id}",
        "app": {"slug": "github-actions"},
    }


def _workflow(run_id: int) -> dict:
    return {"id": run_id, "path": WORKFLOW_PATH, "head_sha": SHA, "event": "pull_request"}


class FailedCiVectors(unittest.TestCase):
    def _evaluate(self, checks: list[dict]):
        run_ids = {check["id"]: int(check["details_url"].split("/")[-3]) for check in checks}

        def fake_workflow_run(_repo: str, check: dict):
            return _workflow(run_ids[check["id"]]), None

        with (
            patch.object(required_checks, "_check_runs", return_value=(checks, None)),
            patch.object(required_checks, "_workflow_run", side_effect=fake_workflow_run),
        ):
            return required_checks.evaluate_required_checks("owner/repo", SHA)

    def test_baseline_success_passes(self):
        ok, reasons, _ = self._evaluate([_check(7, "completed", "success", 70)])
        self.assertTrue(ok, reasons)

    def test_non_success_conclusions_refuse(self):
        for conclusion in ("failure", "cancelled", "timed_out", "action_required", "neutral", "skipped", "stale", None):
            with self.subTest(conclusion=conclusion):
                ok, reasons, evidence = self._evaluate([_check(7, "completed", conclusion, 70)])
                self.assertFalse(ok)
                self.assertTrue(
                    any(f"conclusion {conclusion!r} not in" in reason for reason in reasons), reasons
                )
                self.assertEqual(evidence[0]["conclusion"], conclusion)

    def test_incomplete_run_refuses(self):
        for status in ("queued", "in_progress", "waiting", "pending"):
            with self.subTest(status=status):
                ok, reasons, _ = self._evaluate([_check(7, status, None, 70)])
                self.assertFalse(ok)
                self.assertIn(f"required check validate is not completed (status={status})", reasons)

    def test_newer_failed_rerun_supersedes_earlier_success(self):
        ok, reasons, evidence = self._evaluate(
            [_check(7, "completed", "success", 70), _check(9, "completed", "failure", 90)]
        )
        self.assertFalse(ok)
        self.assertEqual(evidence[0]["id"], 9)
        self.assertTrue(any("'failure'" in reason for reason in reasons), reasons)

    def test_newer_in_progress_rerun_supersedes_earlier_success(self):
        ok, reasons, evidence = self._evaluate(
            [_check(7, "completed", "success", 70), _check(9, "in_progress", None, 90)]
        )
        self.assertFalse(ok)
        self.assertEqual(evidence[0]["id"], 9)

    def test_newer_success_supersedes_earlier_failure(self):
        ok, reasons, evidence = self._evaluate(
            [_check(9, "completed", "success", 90), _check(7, "completed", "failure", 70)]
        )
        self.assertTrue(ok, reasons)
        self.assertEqual(evidence[0]["id"], 9)

    def test_check_runs_read_error_refuses(self):
        with patch.object(required_checks, "_check_runs", return_value=(None, "HTTP 502")):
            ok, reasons, evidence = required_checks.evaluate_required_checks("owner/repo", SHA)
        self.assertFalse(ok)
        self.assertEqual(reasons, ["HTTP 502"])
        self.assertEqual(evidence, [])


if __name__ == "__main__":
    unittest.main()
