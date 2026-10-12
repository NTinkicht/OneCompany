"""OneCompany base-trusted routing: no owner escalation for normal code."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from merge_lane import (
    classify_merge_lane, OWNER, PROTECTED, ROUTINE, MINIMUM_OWNER_PATHS,
)

POLICY = json.loads(
    (Path(__file__).resolve().parents[1] / ".onecompany/governance.json")
    .read_text(encoding="utf-8")
)["control_plane"]


class MergeLaneTests(unittest.TestCase):
    def test_normal_implementation_and_tests_are_not_owner_gated(self):
        lane = classify_merge_lane(
            ["src/feature/quote.py", "tests/test_feature_quote.py"], POLICY
        )
        self.assertEqual(lane["lane"], ROUTINE)
        self.assertFalse(lane["requires_owner"])
        self.assertTrue(lane["requires_exact_head_review"])
        self.assertTrue(lane["requires_exact_head_ci"])

    def test_protected_reviewed_but_not_authority_code_is_distinct(self):
        result = classify_merge_lane(["scripts/first_run_journey.py"], POLICY)
        self.assertEqual(result["lane"], PROTECTED)
        self.assertFalse(result["requires_owner"])

    def test_independent_reviewer_and_merge_authority_are_always_owner_gated(self):
        for file in sorted(MINIMUM_OWNER_PATHS):
            with self.subTest(file=file):
                result = classify_merge_lane([file, "tests/test_some_feature.py"], POLICY)
                self.assertEqual(result["lane"], OWNER)
                self.assertTrue(result["requires_owner"])
                self.assertIn(file, result["owner_paths"])

    def test_existing_l5_and_workflows_remain_owner_gated(self):
        for path in (
            ".l5/control-plane.json", ".github/workflows/test.yml",
            "scripts/l5_shadow_agreement.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(classify_merge_lane([path], POLICY)["lane"], OWNER)

    def test_stronger_human_merge_rule_does_not_change_owner_bypass(self):
        changed = {**POLICY, "human_merge_required": True}
        self.assertEqual(
            classify_merge_lane(["scripts/first_run_journey.py"], changed)["lane"], OWNER
        )
        self.assertEqual(
            classify_merge_lane(["tests/test_regular.py"], changed)["lane"], ROUTINE
        )

    def test_invalid_paths_and_missing_policy_fail_closed(self):
        for paths in ([], ["../scripts/merge.py"], ["/tmp/test"], ["a//b"], [None]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                classify_merge_lane(paths, POLICY)
        with self.assertRaises(ValueError):
            classify_merge_lane(["src/a.py"], {"protected_paths": []})


if __name__ == "__main__":
    unittest.main()
