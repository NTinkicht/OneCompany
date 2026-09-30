import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("l5_recovery", ROOT / "scripts" / "l5_recovery.py")
l5 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(l5)


class L5RecoveryTest(unittest.TestCase):
    def base(self):
        head, base = "a" * 40, "b" * 40
        return {
            "repository":"NTinkicht/OneCompany","issue":251,"canonical_pr":252,"active_prs":[252],
            "head_sha":head,"base_sha":base,"head_current":True,"base_current":True,
            "implementation_complete":True,"emergency_stop":False,"human_only":False,"blocked":False,
            "merged":False,"verified":False,"verified_head_sha":None,"verified_base_sha":None,
            "ci":"SUCCESS","ci_head_sha":head,"ci_base_sha":base,"review":"PASS",
            "review_head_sha":head,"review_base_sha":base,"reviewer_actor":"mistral-vibe",
            "material_authors":["chatgpt"],"material_authors_head_sha":head,"review_eligible":True,
            "unresolved_threads":False,"mergeable":True,"retry_count":0,"retry_action":None,
            "event_id":"evt-1","ready_candidates":[],
        }

    def merged_verified(self):
        return {**self.base(), "active_prs":[], "merged":True, "verified":True,
                "verified_head_sha":"a"*40, "verified_base_sha":"b"*40}

    def test_merge_ready_is_ready_not_mutating(self):
        plan=l5.plan_recovery(self.base())
        self.assertEqual(plan["status"],"READY")
        self.assertEqual(plan["next_action"],"AWAIT_AUTHORIZED_EXPECTED_HEAD_MERGE")
        self.assertFalse(plan["mutation_allowed"])

    def test_ci_red_plans_same_stream_repair(self):
        plan=l5.plan_recovery({**self.base(),"ci":"FAILURE"})
        self.assertEqual(plan["next_action"],"REMEDIATE_SAME_PR_CI")
        self.assertEqual(plan["retry_count_after"],1)
        self.assertEqual(plan["retry_action_after"],"CI")

    def test_review_findings_plan_same_stream_repair(self):
        plan=l5.plan_recovery({**self.base(),"review":"FINDINGS"})
        self.assertEqual(plan["next_action"],"REMEDIATE_SAME_PR_REVIEW")
        self.assertEqual(plan["retry_action_after"],"REVIEW")

    def test_reviewer_outage_plans_eligible_failover(self):
        plan=l5.plan_recovery({**self.base(),"review":"OUTAGE"})
        self.assertEqual(plan["next_action"],"FAILOVER_TO_ELIGIBLE_NONAUTHOR_REVIEWER")
        self.assertEqual(plan["retry_action_after"],"REVIEW")

    def test_stale_head_and_base_reconcile(self):
        self.assertEqual(l5.plan_recovery({**self.base(),"head_current":False})["next_action"],"RECONCILE_HEAD_BASE")
        self.assertEqual(l5.plan_recovery({**self.base(),"base_current":False})["next_action"],"RECONCILE_HEAD_BASE")

    def test_self_review_never_becomes_ready(self):
        self.assertEqual(l5.plan_recovery({**self.base(),"reviewer_actor":"chatgpt"})["next_action"],"DISPATCH_ELIGIBLE_NONAUTHOR_REVIEW")

    def test_duplicate_pr_discovery_blocks(self):
        plan=l5.plan_recovery({**self.base(),"active_prs":[252,253]})
        self.assertEqual(plan["status"],"BLOCKED")
        self.assertEqual(plan["next_action"],"DUPLICATE_STREAM_RECONCILIATION_REQUIRED")

    def test_retry_budget_exhaustion_blocks_ci_scope(self):
        plan=l5.plan_recovery({**self.base(),"ci":"FAILURE","retry_count":l5.MAX_RETRIES,"retry_action":"CI"})
        self.assertEqual(plan["next_action"],"RETRY_BUDGET_EXHAUSTED")

    def test_ci_budget_survives_transient_action_changes(self):
        pending={**self.base(),"ci":"PENDING","retry_count":2,"retry_action":"CI"}
        plan=l5.plan_recovery(pending)
        self.assertEqual(plan["next_action"],"RUN_OR_RECONCILE_EXACT_HEAD_CI")
        self.assertEqual(plan["retry_count_after"],3)
        failed={**self.base(),"ci":"FAILURE","retry_count":3,"retry_action":"CI"}
        self.assertEqual(l5.plan_recovery(failed)["next_action"],"RETRY_BUDGET_EXHAUSTED")

    def test_hold_preserves_retry_budget_and_scope(self):
        hold={**self.base(),"ci":"FAILURE","retry_count":2,"retry_action":"CI","emergency_stop":True}
        plan=l5.plan_recovery(hold)
        self.assertEqual(plan["status"],"BLOCKED")
        self.assertEqual(plan["retry_count"],2)
        self.assertEqual(plan["retry_action"],"CI")

    def test_unknown_retry_scope_fails_closed(self):
        with self.assertRaises(ValueError):
            l5.plan_recovery({**self.base(),"ci":"FAILURE","retry_count":3,"retry_action":"CII"})

    def test_retry_budget_resets_after_phase_transition(self):
        snapshot={**self.base(),"active_prs":[],"merged":True,"verified":False,"retry_count":3,"retry_action":"CI"}
        plan=l5.plan_recovery(snapshot)
        self.assertEqual(plan["next_action"],"VERIFY_MERGED_RESULT")
        self.assertEqual(plan["retry_count"],0)
        self.assertEqual(plan["retry_action_after"],"VERIFY")

    def test_exact_verification_reconciliation_is_bounded(self):
        snapshot={**self.base(),"active_prs":[],"merged":True,"verified":True}
        plan=l5.plan_recovery(snapshot)
        self.assertEqual(plan["next_action"],"RECONCILE_VERIFIED_MERGE_EVIDENCE")
        self.assertEqual(plan["retry_action_after"],"VERIFY")

    def test_positive_retry_count_requires_scope_binding(self):
        with self.assertRaises(ValueError):
            l5.plan_recovery({**self.base(),"ci":"FAILURE","retry_count":1})

    def test_replay_is_idempotent_noop(self):
        first=l5.plan_recovery({**self.base(),"ci":"FAILURE"})
        second=l5.plan_recovery({**self.base(),"ci":"FAILURE"},prior_event_keys={first["event_key"]})
        self.assertEqual(second["status"],"REPLAY_NOOP")

    def test_emergency_stop_and_human_only_block(self):
        self.assertEqual(l5.plan_recovery({**self.base(),"emergency_stop":True})["status"],"BLOCKED")
        self.assertEqual(l5.plan_recovery({**self.base(),"human_only":True})["status"],"BLOCKED")

    def test_verified_merge_replenishes_only_conflict_safe_ready_work(self):
        snapshot={**self.merged_verified(),"ready_candidates":[
            {"issue":90,"ready":True,"blocked":False,"human_only":False,"conflict_safe":False},
            {"issue":95,"ready":True,"blocked":False,"human_only":False,"conflict_safe":True},
            {"issue":99,"ready":True,"blocked":True,"human_only":False,"conflict_safe":True},
        ]}
        plan=l5.plan_recovery(snapshot)
        self.assertEqual(plan["selected_issue"],95)

    def test_unknown_candidate_safety_fails_closed(self):
        for missing in ("ready","blocked","human_only","conflict_safe"):
            candidate={"issue":95,"ready":True,"blocked":False,"human_only":False,"conflict_safe":True}; candidate.pop(missing)
            with self.assertRaises(ValueError):
                l5.plan_recovery({**self.merged_verified(),"ready_candidates":[candidate]})

    def test_empty_ready_queue_idles_without_inventing_work(self):
        plan=l5.plan_recovery(self.merged_verified())
        self.assertEqual(plan["status"],"IDLE")

    def test_journal_normalizes_malformed_refs(self):
        snapshot={**self.base(),"head_sha":"broken","base_sha":"also-broken","ci":"UNKNOWN","review":"UNKNOWN"}
        record=l5.journal_record(snapshot,l5.plan_recovery(snapshot))
        self.assertIsNone(record["head_sha"]); self.assertIsNone(record["base_sha"])

    def test_journal_normalizes_invalid_canonical_pr_on_hold(self):
        snapshot={**self.base(),"canonical_pr":"bad","emergency_stop":True}
        record=l5.journal_record(snapshot,l5.plan_recovery(snapshot))
        self.assertIsNone(record["canonical_pr"])

    def test_journal_record_is_read_only_and_deterministic(self):
        snapshot={**self.base(),"ci":"FAILURE"}; plan=l5.plan_recovery(snapshot)
        self.assertEqual(l5.journal_record(snapshot,plan),l5.journal_record(snapshot,plan))
        self.assertFalse(l5.journal_record(snapshot,plan)["mutation_allowed"])


if __name__=="__main__": unittest.main()
