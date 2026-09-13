from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import github_controls
import governance_validate
import hardening_audit
import required_checks
from onecompany_lib import load_json, path_matches_any


class KernelHardeningTests(unittest.TestCase):
    def test_future_executable_paths_are_structurally_protected(self):
        governance = load_json(ROOT / ".onecompany" / "governance.json")
        patterns = governance["control_plane"]["protected_paths"]
        for path in (
            ".onecompany/selftest/new_test.py",
            "scripts/new_helper.py",
            ".github/workflows/new-workflow.yml",
            "company/new_kernel_policy.md",
        ):
            self.assertTrue(path_matches_any(path, patterns), path)

    def test_every_current_ci_executable_path_is_protected(self):
        governance = load_json(ROOT / ".onecompany" / "governance.json")
        patterns = governance["control_plane"]["protected_paths"]
        missing = sorted(
            path
            for path in governance_validate.executable_control_plane_paths()
            if not path_matches_any(path, patterns)
        )
        self.assertEqual(missing, [])

    def test_required_check_manifest_binds_validate_to_trusted_workflow(self):
        manifest = required_checks.required_check_manifest()
        self.assertEqual(required_checks.required_check_names(), ["validate"])
        self.assertEqual(manifest["checks"][0]["workflow_path"], ".github/workflows/onecompany-validate.yml")

    def test_missing_required_check_fails_closed(self):
        with patch.object(required_checks, "_check_runs", return_value=([], None)):
            ok, reasons, evidence = required_checks.evaluate_required_checks("owner/repo", "a" * 40)
        self.assertFalse(ok)
        self.assertTrue(any("missing" in reason for reason in reasons))
        self.assertEqual(evidence, [])

    def test_exact_sha_successful_trusted_check_passes(self):
        sha = "a" * 40
        check = {
            "id": 7,
            "name": "validate",
            "head_sha": sha,
            "status": "completed",
            "conclusion": "success",
            "details_url": "https://github.com/owner/repo/actions/runs/70/job/700",
            "app": {"slug": "github-actions"},
        }
        workflow = {
            "id": 70,
            "path": ".github/workflows/onecompany-validate.yml",
            "head_sha": sha,
            "event": "pull_request",
        }
        with (
            patch.object(required_checks, "_check_runs", return_value=([check], None)),
            patch.object(required_checks, "_workflow_run", return_value=(workflow, None)),
        ):
            ok, reasons, evidence = required_checks.evaluate_required_checks("owner/repo", sha)
        self.assertTrue(ok, reasons)
        self.assertEqual(reasons, [])
        self.assertEqual(evidence[0]["id"], 7)
        self.assertEqual(evidence[0]["workflow_path"], ".github/workflows/onecompany-validate.yml")

    def test_same_name_check_from_untrusted_workflow_cannot_supersede_referee(self):
        sha = "a" * 40
        genuine = {
            "id": 8,
            "name": "validate",
            "head_sha": sha,
            "status": "completed",
            "conclusion": "failure",
            "details_url": "https://github.com/owner/repo/actions/runs/80/job/800",
            "app": {"slug": "github-actions"},
        }
        forged = {
            "id": 99,
            "name": "validate",
            "head_sha": sha,
            "status": "completed",
            "conclusion": "success",
            "details_url": "https://github.com/owner/repo/actions/runs/99/job/990",
            "app": {"slug": "github-actions"},
        }

        def workflow_for(_repo, check):
            if check["id"] == 8:
                return ({"id": 80, "path": ".github/workflows/onecompany-validate.yml", "head_sha": sha}, None)
            return ({"id": 99, "path": ".github/workflows/forged.yml", "head_sha": sha}, None)

        with (
            patch.object(required_checks, "_check_runs", return_value=([genuine, forged], None)),
            patch.object(required_checks, "_workflow_run", side_effect=workflow_for),
        ):
            ok, reasons, evidence = required_checks.evaluate_required_checks("owner/repo", sha)
        self.assertFalse(ok)
        self.assertEqual(evidence[0]["id"], 8)
        self.assertTrue(any("conclusion" in reason for reason in reasons), reasons)

    def test_check_from_wrong_sha_fails(self):
        expected_sha = "a" * 40
        check = {
            "id": 8,
            "name": "validate",
            "head_sha": "b" * 40,
            "status": "completed",
            "conclusion": "success",
            "details_url": "https://github.com/owner/repo/actions/runs/80/job/800",
            "app": {"slug": "github-actions"},
        }
        workflow = {
            "id": 80,
            "path": ".github/workflows/onecompany-validate.yml",
            "head_sha": expected_sha,
        }
        with (
            patch.object(required_checks, "_check_runs", return_value=([check], None)),
            patch.object(required_checks, "_workflow_run", return_value=(workflow, None)),
        ):
            ok, reasons, _ = required_checks.evaluate_required_checks("owner/repo", expected_sha)
        self.assertFalse(ok)
        self.assertTrue(any("exact SHA" in reason for reason in reasons))

    def test_hardening_audit_rejects_unpinned_action_in_any_workflow_name(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = Path(tmp) / "deploy.yml"
            path.write_text("name: deploy\nsteps:\n  - uses: actions/checkout@v4\n", encoding="utf-8")
            errors = hardening_audit.audit_workflow(path)
        self.assertTrue(any("not pinned" in error for error in errors), errors)

    def test_hardening_audit_rejects_flow_syntax_bypasses(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = Path(tmp) / "deploy.yml"
            path.write_text(
                "name: deploy\non: [pull_request_target]\njobs: {x: {steps: [{ uses: actions/checkout@v4 }]}}\n",
                encoding="utf-8",
            )
            errors = hardening_audit.audit_workflow(path)
        self.assertTrue(any("pull_request_target" in error for error in errors), errors)
        self.assertTrue(any("not pinned" in error for error in errors), errors)

    def test_hardening_audit_accepts_sha_pinned_action(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = Path(tmp) / "ci.yml"
            path.write_text(
                "name: ci\nsteps:\n  - uses: actions/checkout@" + "a" * 40 + "\n",
                encoding="utf-8",
            )
            errors = hardening_audit.audit_workflow(path)
        self.assertEqual(errors, [])

    def test_ruleset_exclusion_patterns_take_precedence(self):
        ruleset = {
            "conditions": {
                "ref_name": {
                    "include": ["~ALL"],
                    "exclude": ["refs/heads/main*"],
                }
            }
        }
        self.assertFalse(github_controls._ruleset_applies_to_branch(ruleset, "main"))
        self.assertTrue(github_controls._ruleset_applies_to_branch(ruleset, "release"))

    def test_codeowners_covers_every_governance_path_family(self):
        text = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        ok, missing = github_controls._codeowners_coverage(text)
        self.assertTrue(ok, missing)
        self.assertEqual(missing, [])

    def test_codeowners_missing_protected_family_fails_coverage(self):
        ok, missing = github_controls._codeowners_coverage("/.onecompany/ @owner\n/scripts/ @owner\n")
        self.assertFalse(ok)
        self.assertIn("/.github/", missing)


if __name__ == "__main__":
    unittest.main()
