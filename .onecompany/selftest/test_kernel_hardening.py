from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

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

    def test_required_check_manifest_names_real_validate_job(self):
        self.assertEqual(required_checks.required_check_names(), ["validate"])

    def test_missing_required_check_fails_closed(self):
        with patch.object(required_checks, "_check_runs", return_value=([], None)):
            ok, reasons, evidence = required_checks.evaluate_required_checks("owner/repo", "a" * 40)
        self.assertFalse(ok)
        self.assertTrue(any("missing" in reason for reason in reasons))
        self.assertEqual(evidence, [])

    def test_exact_sha_successful_check_passes(self):
        sha = "a" * 40
        check = {
            "id": 7,
            "name": "validate",
            "head_sha": sha,
            "status": "completed",
            "conclusion": "success",
            "details_url": "https://example.invalid/check/7",
            "app": {"slug": "github-actions"},
        }
        with patch.object(required_checks, "_check_runs", return_value=([check], None)):
            ok, reasons, evidence = required_checks.evaluate_required_checks("owner/repo", sha)
        self.assertTrue(ok, reasons)
        self.assertEqual(reasons, [])
        self.assertEqual(evidence[0]["id"], 7)

    def test_check_from_wrong_sha_fails(self):
        check = {
            "id": 8,
            "name": "validate",
            "head_sha": "b" * 40,
            "status": "completed",
            "conclusion": "success",
            "app": {"slug": "github-actions"},
        }
        with patch.object(required_checks, "_check_runs", return_value=([check], None)):
            ok, reasons, _ = required_checks.evaluate_required_checks("owner/repo", "a" * 40)
        self.assertFalse(ok)
        self.assertTrue(any("exact SHA" in reason for reason in reasons))

    def test_hardening_audit_rejects_unpinned_action_in_any_workflow_name(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = Path(tmp) / "deploy.yml"
            path.write_text("name: deploy\nsteps:\n  - uses: actions/checkout@v4\n", encoding="utf-8")
            errors = hardening_audit.audit_workflow(path)
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


if __name__ == "__main__":
    unittest.main()
