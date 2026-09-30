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
        head = "a" * 40
        base = "b" * 40
        return {
            "repository": "NTinkicht/OneCompany",
            "issue": 249,
            "canonical_pr": 250,
            "active_prs": [250],
            "head_sha": head,
            "base_sha": base,
            "head_current": True,
            "base_current": True,
            "implementation_complete": True,
            "emergency_stop": False,
            "human_only": False,
            "blocked": False,
            "merged": False,
            "verified": False,
            "verified_head_sha": None,
            "verified_base_sha": None,
            "ci_head_sha": head,
            "ci_base_sha": base,
            "review_head_sha": head,
            "review_base_sha": base,
            "reviewer_actor": "mistral-vibe",
            "material_authors": ["chatgpt"],
            "material_authors_head_sha": head,
            "review_eligible": True,
            "unresolved_threads": False,
        }

    def ready(self):
        return {**self.base(), "ci": "SUCCESS", "review": "PASS", "mergeable": True}

    def test_happy_path_reaches_merge_ready_without_mutation_authority(self):
        result = l5.reduce_evidence(self.ready())
        self.assertEqual(result["state"], "MERGE_READY")
        self.assertEqual(result["next_action"], "AWAIT_AUTHORIZED_EXPECTED_HEAD_MERGE")
        self.assertFalse(result["mutation_allowed"])

    def test_unknown_safety_controls_fail_closed(self):
        for field in ("emergency_stop", "human_only", "blocked", "unresolved_threads"):
            sample = self.ready()
            sample.pop(field)
            with self.assertRaises(ValueError):
                l5.reduce_evidence(sample)

    def test_head_and_base_freshness_must_be_affirmative(self):
        for field in ("head_current", "base_current"):
            missing = self.ready()
            missing.pop(field)
            with self.assertRaises(ValueError):
                l5.reduce_evidence(missing)
            stale = self.ready()
            stale[field] = False
            self.assertEqual(l5.reduce_evidence(stale)["next_action"], "RECONCILE_HEAD_BASE")

    def test_ci_success_must_bind_current_head_and_base(self):
        stale = self.ready()
        stale["ci_head_sha"] = "c" * 40
        self.assertEqual(l5.reduce_evidence(stale)["next_action"], "RECONCILE_EXACT_HEAD_CI_EVIDENCE")

    def test_review_pass_must_bind_current_head_and_base(self):
        stale = self.ready()
        stale["review_base_sha"] = "c" * 40
        self.assertEqual(l5.reduce_evidence(stale)["next_action"], "RECONCILE_EXACT_HEAD_REVIEW_EVIDENCE")

    def test_review_pass_requires_eligible_non_author(self):
        self_review = self.ready()
        self_review["reviewer_actor"] = "chatgpt"
        self.assertEqual(l5.reduce_evidence(self_review)["next_action"], "DISPATCH_ELIGIBLE_NONAUTHOR_REVIEW")
        ineligible = self.ready()
        ineligible["review_eligible"] = False
        self.assertEqual(l5.reduce_evidence(ineligible)["next_action"], "DISPATCH_ELIGIBLE_NONAUTHOR_REVIEW")

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

    def test_vanished_unmerged_canonical_stream_fails_closed(self):
        result = l5.reduce_evidence({**self.base(), "active_prs": []})
        self.assertEqual(result["state"], "IMPLEMENTING")
        self.assertEqual(result["next_action"], "RECONCILE_CANONICAL_PR")

    def test_post_merge_requires_closed_stream_then_verification(self):
        inconsistent = l5.reduce_evidence({**self.base(), "merged": True, "verified": True})
        verifying = l5.reduce_evidence({**self.base(), "active_prs": [], "merged": True, "verified": False})
        complete = l5.reduce_evidence({
            **self.base(),
            "active_prs": [],
            "merged": True,
            "verified": True,
            "verified_head_sha": "a" * 40,
            "verified_base_sha": "b" * 40,
        })
        self.assertEqual(inconsistent["next_action"], "RECONCILE_POST_MERGE_STREAM_STATE")
        self.assertEqual(verifying["state"], "VERIFYING")
        self.assertEqual(complete["state"], "COMPLETE")
        self.assertEqual(complete["next_action"], "REPLENISH_NEXT_READY_WU")

    def test_human_only_and_emergency_stop_never_progress(self):
        self.assertEqual(l5.reduce_evidence({**self.base(), "human_only": True})["next_action"], "HUMAN_OR_POLICY_BLOCKED")
        self.assertEqual(l5.reduce_evidence({**self.base(), "emergency_stop": True})["next_action"], "EMERGENCY_STOP_HOLD")


if __name__ == "__main__":
    unittest.main()
