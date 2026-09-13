from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import github_controls
import hardening_audit
import required_checks


class KernelReviewRegressionTests(unittest.TestCase):
    def test_base_trusted_workflow_change_blocks_candidate_self_attestation(self):
        manifest = {
            "checks": [
                {
                    "name": "validate",
                    "allowed_conclusions": ["success"],
                    "app_slug": "github-actions",
                    "workflow_path": ".github/workflows/onecompany-validate.yml",
                }
            ]
        }
        with (
            patch.object(required_checks, "_manifest_from_ref", return_value=(manifest, None)),
            patch.object(
                required_checks,
                "_verify_trusted_workflow_unchanged",
                return_value=(
                    False,
                    "base-blob",
                    "trusted workflow changed relative to base; candidate CI cannot self-attest that change",
                ),
            ),
            patch.object(required_checks, "_check_runs") as check_runs,
        ):
            ok, reasons, evidence = required_checks.evaluate_required_checks(
                "owner/repo", "a" * 40, trusted_ref="b" * 40
            )
        self.assertFalse(ok)
        self.assertTrue(any("self-attest" in reason for reason in reasons), reasons)
        self.assertEqual(evidence, [])
        check_runs.assert_not_called()

    def test_base_trusted_manifest_and_unchanged_workflow_can_validate_exact_sha(self):
        sha = "a" * 40
        base = "b" * 40
        manifest = {
            "checks": [
                {
                    "name": "validate",
                    "allowed_conclusions": ["success"],
                    "app_slug": "github-actions",
                    "workflow_path": ".github/workflows/onecompany-validate.yml",
                }
            ]
        }
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
            patch.object(required_checks, "_manifest_from_ref", return_value=(manifest, None)),
            patch.object(
                required_checks,
                "_verify_trusted_workflow_unchanged",
                return_value=(True, "trusted-workflow-blob", None),
            ),
            patch.object(required_checks, "_check_runs", return_value=([check], None)),
            patch.object(required_checks, "_workflow_run", return_value=(workflow, None)),
        ):
            ok, reasons, evidence = required_checks.evaluate_required_checks(
                "owner/repo", sha, trusted_ref=base
            )
        self.assertTrue(ok, reasons)
        self.assertEqual(evidence[0]["trusted_ref"], base)
        self.assertEqual(evidence[0]["trusted_workflow_blob_sha"], "trusted-workflow-blob")

    def test_hardening_audit_rejects_unicode_encoded_yaml_key(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = Path(tmp) / "encoded.yml"
            path.write_text(
                'name: encoded\nsteps:\n  - { "\\u0075ses": actions/checkout@v4 }\n',
                encoding="utf-8",
            )
            errors = hardening_audit.audit_workflow(path)
        self.assertTrue(any("escapes are forbidden" in error for error in errors), errors)
        self.assertTrue(any("not pinned" in error for error in errors), errors)

    def test_unsupported_ruleset_exclusion_fails_closed(self):
        ruleset = {
            "conditions": {
                "ref_name": {
                    "include": ["~ALL"],
                    "exclude": ["refs/heads/[m]ain"],
                }
            }
        }
        self.assertFalse(github_controls._ruleset_applies_to_branch(ruleset, "main"))

    def test_later_ownerless_codeowners_rule_removes_effective_ownership(self):
        text = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        text += "\n/scripts/gate.py\n"
        ok, missing = github_controls._codeowners_coverage(text)
        self.assertFalse(ok)
        self.assertIn("/scripts/gate.py", missing)


if __name__ == "__main__":
    unittest.main()
