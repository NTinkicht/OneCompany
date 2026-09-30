import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "l5_state_machine.py"
SPEC = importlib.util.spec_from_file_location("l5_state_machine", MODULE_PATH)
l5 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(l5)


class L5StateMachineTest(unittest.TestCase):
    def base(self):
        return {
            "repository": "NTinkicht/OneCompany",
            "issue": 249,
            "canonical_pr": 250,
            "active_prs": [250],
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "head_current": True,
            "base_current": True,
            "implementation_complete": True,
        }

    def test_happy_path_reaches_merge_ready_without_mutation_authority(self):
        result = l5.reduce_evidence({**self.base(), "ci": "SUCCESS", "review": "PASS", "mergeable": True})
        self.assertEqual(result["state"], "MERGE_READY")
        self.assertEqual(result["next_action"], "AWAIT_AUTHORIZED_EXPECTED_HEAD_MERGE")
        self.assertFalse(result["mutation_allowed"])

    def test_ci_failure_remediates_same_pr(self):
        result = l5.reduce_evidence({**self.base(), "ci": "FAILURE"})
        self.assertEqual(result["state"], "REMEDIATING")
        self.assertEqual(result["next_action"], "REMEDIATE_SAME_PR_CI")

    def test_reviewer_outage_plans_failover(self):
        result = l5.reduce_evidence({**self.base(), "ci": "SUCCESS", "review": "OUTAGE"})
        self.assertEqual(result["state"], "REVIEWING")
        self.assertEqual(result["next_action"], "FAILOVER_TO_ELIGIBLE_NONAUTHOR_REVIEWER")

    def test_duplicate_stream_fails_closed(self):
        result = l5.reduce_evidence({**self.base(), "active_prs": [250, 251]})
        self.assertEqual(result["next_action"], "DUPLICATE_STREAM_RECONCILIATION_REQUIRED")

    def test_stale_refs_fail_closed(self):
        result = l5.reduce_evidence({**self.base(), "head_current": False})
        self.assertEqual(result["next_action"], "RECONCILE_HEAD_BASE")

    def test_post_merge_requires_verification_before_replenishment(self):
        verifying = l5.reduce_evidence({**self.base(), "merged": True, "verified": False})
        complete = l5.reduce_evidence({**self.base(), "merged": True, "verified": True})
        self.assertEqual(verifying["state"], "VERIFYING")
        self.assertEqual(complete["state"], "COMPLETE")
        self.assertEqual(complete["next_action"], "REPLENISH_NEXT_READY_WU")

    def test_human_only_and_emergency_stop_never_progress(self):
        self.assertEqual(l5.reduce_evidence({**self.base(), "human_only": True})["next_action"], "HUMAN_OR_POLICY_BLOCKED")
        self.assertEqual(l5.reduce_evidence({**self.base(), "emergency_stop": True})["next_action"], "EMERGENCY_STOP_HOLD")


if __name__ == "__main__":
    unittest.main()
