from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import handoff  # noqa: E402


class HandoffTests(unittest.TestCase):
    def _policy(self) -> dict:
        return copy.deepcopy(handoff.load_policy())

    def _hint(self, kind: str, event_id: str = "event-1") -> dict:
        return {
            "event_id": event_id,
            "kind": kind,
            "subject": "WU-B2-001",
            "payload": {"head": "attacker-selected", "authority": "grant"},
        }

    def _snapshot(self, state: dict, transition_kind: str | None = None) -> dict:
        value = {
            "repository": "NTinkicht/OneCompany",
            "emergency_stop": False,
            "zero_spend_ok": True,
            "subject_state": state,
        }
        if transition_kind:
            value["transition_kind"] = transition_kind
        return value

    def _ready_state(self) -> dict:
        return {
            "work_unit": "WU-B2-001",
            "status": "READY",
            "dependencies_satisfied": True,
            "active_writer_count": 0,
            "route_eligible": True,
        }

    def test_default_policy_is_staged_and_not_activation_ready(self):
        policy = self._policy()
        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["mode"], "staged_only")
        self.assertFalse(handoff.activation_ready(policy))
        self.assertEqual(policy["publisher_policy"]["automation_publishers"], {})

    def test_duplicate_ready_deliveries_converge_on_one_proposal_identity(self):
        snapshot = self._snapshot(self._ready_state())
        first = handoff.reconcile_hint(self._hint("WORK_READY", "delivery-a"), snapshot)
        second = handoff.reconcile_hint(self._hint("WORK_READY", "delivery-b"), snapshot)
        self.assertEqual(first["action"], "DISPATCH_PROPOSAL")
        self.assertEqual(first["idempotency_key"], second["idempotency_key"])
        self.assertFalse(first["may_mutate"])
        self.assertEqual(first["activation_state"], "STAGED_BLOCKED")

    def test_two_handlers_cannot_create_a_second_writer(self):
        state = self._ready_state()
        state["active_writer_count"] = 1
        result = handoff.reconcile_hint(self._hint("WORK_READY"), self._snapshot(state))
        self.assertEqual(result["action"], "NO_ACTION")
        self.assertIn("canonical_writer_already_exists", result["reasons"])

    def test_hint_payload_cannot_override_authoritative_pr_head(self):
        state = {
            "pr": 59,
            "head": "a" * 40,
            "base": "b" * 40,
            "ci_state": "success",
        }
        hint = self._hint("CI_CHANGED")
        hint["payload"] = {"head": "c" * 40, "ci_state": "success", "authority": "merge"}
        result = handoff.reconcile_hint(hint, self._snapshot(state))
        self.assertEqual(result["authoritative_state"]["head"], "a" * 40)
        self.assertFalse(result["hint_payload_used_as_authority"])
        self.assertEqual(result["authority_effects"], [])

    def test_stale_review_identity_cannot_advance_promotion(self):
        state = {
            "pr": 59,
            "head": "a" * 40,
            "base": "b" * 40,
            "review_head": "c" * 40,
            "review_base": "b" * 40,
            "independent": True,
            "human_code_owner_required": True,
            "human_code_owner_approved": True,
        }
        result = handoff.reconcile_hint(self._hint("REVIEW_CHANGED"), self._snapshot(state))
        self.assertEqual(result["action"], "NO_ACTION")
        self.assertIn("stale_review_identity", result["reasons"])

    def test_human_code_owner_requirement_remains_human(self):
        state = {
            "pr": 59,
            "head": "a" * 40,
            "base": "b" * 40,
            "review_head": "a" * 40,
            "review_base": "b" * 40,
            "independent": True,
            "human_code_owner_required": True,
            "human_code_owner_approved": False,
        }
        result = handoff.reconcile_hint(self._hint("REVIEW_CHANGED"), self._snapshot(state))
        self.assertEqual(result["action"], "HUMAN_GATE_PENDING")
        self.assertFalse(result["may_mutate"])

    def test_emergency_stop_blocks_consequential_handoff(self):
        snapshot = self._snapshot(self._ready_state())
        snapshot["emergency_stop"] = True
        result = handoff.reconcile_hint(self._hint("WORK_READY"), snapshot)
        self.assertEqual(result["action"], "STOPPED")
        self.assertIn("emergency_stop_active", result["reasons"])

    def test_emergency_stop_still_allows_read_only_pr_reconciliation(self):
        state = {"pr": 59, "head": "a" * 40, "base": "b" * 40}
        snapshot = self._snapshot(state)
        snapshot["emergency_stop"] = True
        result = handoff.reconcile_hint(self._hint("PR_CHANGED"), snapshot)
        self.assertEqual(result["action"], "EVIDENCE_RECONCILE")
        self.assertFalse(result["may_mutate"])

    def test_zero_spend_failure_blocks_dispatch_proposal(self):
        snapshot = self._snapshot(self._ready_state())
        snapshot["zero_spend_ok"] = False
        result = handoff.reconcile_hint(self._hint("WORK_READY"), snapshot)
        self.assertEqual(result["action"], "CAPACITY_BLOCKED")
        self.assertIn("zero_extra_spend_not_verified", result["reasons"])

    def test_merge_replay_does_not_unblock_successor_twice(self):
        state = {
            "pr": 59,
            "head": "a" * 40,
            "base": "b" * 40,
            "verified": True,
            "already_processed": True,
            "successors": ["WU-NEXT"],
        }
        result = handoff.reconcile_hint(self._hint("MERGE_CHANGED"), self._snapshot(state))
        self.assertEqual(result["action"], "NO_ACTION")
        self.assertIn("merge_already_processed", result["reasons"])

    def test_verified_merge_proposes_successor_discovery_only(self):
        state = {
            "pr": 59,
            "head": "a" * 40,
            "base": "b" * 40,
            "verified": True,
            "already_processed": False,
            "successors": ["WU-NEXT"],
        }
        result = handoff.reconcile_hint(self._hint("MERGE_CHANGED"), self._snapshot(state))
        self.assertEqual(result["action"], "SUCCESSOR_DISCOVERY")
        self.assertTrue(result["proposal_only"])
        self.assertFalse(result["may_mutate"])

    def test_lost_event_is_recoverable_by_later_reconciliation(self):
        snapshot = self._snapshot(self._ready_state(), transition_kind="WORK_READY")
        direct = handoff.reconcile_hint(self._hint("WORK_READY", "lost-delivery"), snapshot)
        recovered = handoff.reconcile_hint(self._hint("RECONCILE", "later-scan"), snapshot)
        self.assertEqual(direct["action"], recovered["action"])
        self.assertEqual(direct["idempotency_key"], recovered["idempotency_key"])

    def test_publisher_identity_and_event_type_are_both_scoped(self):
        policy = self._policy()
        policy["publisher_policy"]["automation_publishers"] = {
            "onecompany-bot": ["SUPERVISION_CHECK"]
        }
        hint = self._hint("PR_CHANGED")
        hint["publisher"] = "onecompany-bot"
        hint["event_type"] = "SUPERVISION_CHECK"
        state = {"pr": 59, "head": "a" * 40, "base": "b" * 40}
        accepted = handoff.reconcile_hint(hint, self._snapshot(state), policy=policy)
        self.assertEqual(accepted["action"], "EVIDENCE_RECONCILE")

        forbidden = copy.deepcopy(hint)
        forbidden["event_type"] = "MERGED"
        with self.assertRaisesRegex(handoff.HandoffError, "not_allowlisted"):
            handoff.reconcile_hint(forbidden, self._snapshot(state), policy=policy)

        untrusted = copy.deepcopy(hint)
        untrusted["publisher"] = "other-bot"
        with self.assertRaisesRegex(handoff.HandoffError, "not_allowlisted"):
            handoff.reconcile_hint(untrusted, self._snapshot(state), policy=policy)

    def test_canonical_lease_requires_exactly_one_writer(self):
        state = {
            "work_unit": "WU-B2-001",
            "canonical": True,
            "role": "implementation",
            "actor": "chatgpt",
            "branch": "wu-b2",
            "pr": 60,
            "dispatch_eligible": True,
            "active_writer_count": 1,
        }
        result = handoff.reconcile_hint(self._hint("LEASE_CHANGED"), self._snapshot(state))
        self.assertEqual(result["action"], "EXECUTION_PROPOSAL")
        self.assertFalse(result["may_mutate"])
        state["active_writer_count"] = 2
        blocked = handoff.reconcile_hint(self._hint("LEASE_CHANGED"), self._snapshot(state))
        self.assertEqual(blocked["action"], "NO_ACTION")
        self.assertIn("canonical_writer_count_not_one", blocked["reasons"])


if __name__ == "__main__":
    unittest.main()
