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

    def test_non_author_review_is_separate_from_github_check_enforcement(self):
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
        self.assertTrue(result["enforcement_ok"])

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
