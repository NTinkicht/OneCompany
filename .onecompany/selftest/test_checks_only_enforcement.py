from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import github_controls as controls


class ChecksOnlyEnforcementTests(unittest.TestCase):
    """Require technical checks without manufacturing individual review gates."""

    def api(self, path: str):
        """Return representative branch-level and ruleset GitHub metadata."""
        if "/contents/.github/CODEOWNERS?" in path:
            return (
                0,
                {"encoding": "base64", "content": base64.b64encode(
                    b"/scripts/ @NTinkicht\n"
                ).decode("ascii")},
                "",
            )
        if "/codeowners/errors?" in path:
            return 0, {"errors": []}, ""
        if path.endswith("/protection"):
            return 1, None, "no classic protection"
        if path.endswith("/rulesets"):
            return 0, [{"id": 1, "enforcement": "active"}], ""
        if path.endswith("/rulesets/1"):
            return 0, {
                "id": 1, "name": "checks-only",
                "enforcement": "active",
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
                "bypass_actors": [],
                "rules": [{
                    "type": "required_status_checks",
                    "parameters": {"required_status_checks": [
                        {"context": "validate"},
                    ]},
                }],
            }, ""
        raise AssertionError(path)

    def test_checks_only_does_not_enforce_independent_review(self):
        """Pass non-bypassable technical checks without a Code Owner rule."""
        with (
            patch.object(controls, "gh_api", side_effect=self.api),
            patch.object(
                controls, "_codeowners_coverage", return_value=(True, []),
            ),
        ):
            result = controls.inspect_enforcement(
                "example/app", "main", {"validate"},
            )
        self.assertTrue(result["codeowners_valid"])
        self.assertFalse(result["code_owner_review_enforced"])
        self.assertEqual(result["missing_required_checks"], [])
        self.assertFalse(result["review_gate_enforced"])
        self.assertFalse(result["enforcement_ok"])

    def test_pinned_review_app_status_check_enforces_independence(self):
        """Permit an independently vetted app, not a candidate-controlled name."""
        original = self.api
        def pinned_api(path):
            """Require the exact review App for the non-bypassable ruleset."""
            code, payload, error = original(path)
            if path.endswith("/rulesets/1"):
                payload["rules"][0]["parameters"]["required_status_checks"].append({
                    "context": controls.REVIEW_GATE_CONTEXT,
                    "integration_id": 117,
                })
            return code, payload, error
        with (
            patch.object(controls, "gh_api", side_effect=pinned_api),
            patch.object(controls, "_codeowners_coverage", return_value=(True, [])),
            patch.object(controls, "REVIEW_GATE_APP_ID", 117),
        ):
            result = controls.inspect_enforcement(
                "example/app", "main", {"validate"},
            )
        self.assertTrue(result["review_gate_enforced"])
        self.assertTrue(result["enforcement_ok"])

    def test_wrong_review_app_cannot_fake_attestation(self):
        """Reject status context published by the wrong GitHub integration."""
        original = self.api
        def foreign_api(path):
            """Return a same-named status check from an unauthorized app."""
            code, payload, error = original(path)
            if path.endswith("/rulesets/1"):
                payload["rules"][0]["parameters"]["required_status_checks"].append({
                    "context": controls.REVIEW_GATE_CONTEXT,
                    "integration_id": 999,
                })
            return code, payload, error
        with (
            patch.object(controls, "gh_api", side_effect=foreign_api),
            patch.object(controls, "_codeowners_coverage", return_value=(True, [])),
            patch.object(controls, "REVIEW_GATE_APP_ID", 117),
        ):
            result = controls.inspect_enforcement(
                "example/app", "main", {"validate"},
            )
        self.assertFalse(result["review_gate_enforced"])
        self.assertFalse(result["enforcement_ok"])

    def test_missing_required_check_is_a_blocker_even_without_review_gate(self):
        """Keep exact-head status checks mechanically required."""
        with (
            patch.object(controls, "gh_api", side_effect=self.api),
            patch.object(
                controls, "_codeowners_coverage", return_value=(True, []),
            ),
        ):
            result = controls.inspect_enforcement(
                "example/app", "main", {"validate", "security-scan"},
            )
        self.assertFalse(result["enforcement_ok"])
        self.assertEqual(result["missing_required_checks"], ["security-scan"])


if __name__ == "__main__":
    unittest.main()
