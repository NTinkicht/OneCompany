from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import handoff  # noqa: E402
import handoff_runtime  # noqa: E402


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

    def test_policy_is_active_with_protected_main_evidence(self):
        policy = self._policy()
        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["mode"], "active")
        self.assertTrue(handoff.activation_ready(policy))
        self.assertTrue(policy["activation"]["b1_protected_main_proven"])
        self.assertTrue(policy["activation"]["ledger_replay_proven"])
        self.assertGreaterEqual(len(policy["activation"]["evidence_refs"]), 3)
        self.assertFalse(policy["runtime"]["automatic_failover_allowed"])
        self.assertFalse(policy["runtime"]["automatic_merge_allowed"])

    def test_duplicate_ready_deliveries_converge_on_one_proposal_identity(self):
        snapshot = self._snapshot(self._ready_state())
        first = handoff.reconcile_hint(self._hint("WORK_READY", "delivery-a"), snapshot)
        second = handoff.reconcile_hint(self._hint("WORK_READY", "delivery-b"), snapshot)
        self.assertEqual(first["action"], "DISPATCH_PROPOSAL")
        self.assertEqual(first["idempotency_key"], second["idempotency_key"])
        self.assertFalse(first["may_mutate"])
        self.assertEqual(first["activation_state"], "PROPOSAL_READY")

    def test_two_handlers_cannot_create_a_second_writer(self):
        state = self._ready_state()
        state["active_writer_count"] = 1
        result = handoff.reconcile_hint(self._hint("WORK_READY"), self._snapshot(state))
        self.assertEqual(result["action"], "NO_ACTION")
        self.assertIn("canonical_writer_already_exists", result["reasons"])

    def test_hint_payload_cannot_override_authoritative_pr_head(self):
        state = {"pr": 59, "head": "a" * 40, "base": "b" * 40, "ci_state": "success"}
        hint = self._hint("CI_CHANGED")
        hint["payload"] = {"head": "c" * 40, "ci_state": "success", "authority": "merge"}
        result = handoff.reconcile_hint(hint, self._snapshot(state))
        self.assertEqual(result["authoritative_state"]["head"], "a" * 40)
        self.assertFalse(result["hint_payload_used_as_authority"])
        self.assertEqual(result["authority_effects"], [])

    def test_stale_review_and_missing_human_gate_cannot_advance(self):
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
        state["review_head"] = state["head"]
        state["human_code_owner_approved"] = False
        pending = handoff.reconcile_hint(self._hint("REVIEW_CHANGED"), self._snapshot(state))
        self.assertEqual(pending["action"], "HUMAN_GATE_PENDING")
        self.assertFalse(pending["may_mutate"])

    def test_emergency_stop_and_zero_spend_block_consequential_handoffs(self):
        snapshot = self._snapshot(self._ready_state())
        snapshot["emergency_stop"] = True
        stopped = handoff.reconcile_hint(self._hint("WORK_READY"), snapshot)
        self.assertEqual(stopped["action"], "STOPPED")
        snapshot["emergency_stop"] = False
        snapshot["zero_spend_ok"] = False
        blocked = handoff.reconcile_hint(self._hint("WORK_READY"), snapshot)
        self.assertEqual(blocked["action"], "CAPACITY_BLOCKED")

    def test_merge_replay_and_lost_event_are_idempotent(self):
        merged = {
            "pr": 59,
            "head": "a" * 40,
            "base": "b" * 40,
            "verified": True,
            "already_processed": True,
            "successors": ["WU-NEXT"],
        }
        replay = handoff.reconcile_hint(self._hint("MERGE_CHANGED"), self._snapshot(merged))
        self.assertEqual(replay["action"], "NO_ACTION")
        snapshot = self._snapshot(self._ready_state(), transition_kind="WORK_READY")
        direct = handoff.reconcile_hint(self._hint("WORK_READY", "lost"), snapshot)
        recovered = handoff.reconcile_hint(self._hint("RECONCILE", "later"), snapshot)
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
        state["active_writer_count"] = 2
        blocked = handoff.reconcile_hint(self._hint("LEASE_CHANGED"), self._snapshot(state))
        self.assertIn("canonical_writer_count_not_one", blocked["reasons"])

    def test_runtime_payload_is_only_a_wake_hint(self):
        payload = {
            "pull_request": {"number": 61, "head": {"sha": "attacker"}},
            "authority": "merge",
        }
        self.assertEqual(handoff_runtime.event_kind("pull_request", "synchronize", payload), "PR_CHANGED")
        self.assertEqual(handoff_runtime.event_subject("pull_request", payload), "pr:61")
        first = handoff_runtime.wake_id("delivery", "pull_request", "synchronize", "pr:61")
        second = handoff_runtime.wake_id("delivery", "pull_request", "synchronize", "pr:61")
        self.assertEqual(first, second)

    def test_runtime_supervision_posts_with_one_invocation(self):
        """Use one live supervision snapshot when Team Room posting is enabled."""
        with patch.object(handoff_runtime.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"action":"RECONCILE"}'
            run.return_value.stderr = ""
            snapshot = handoff_runtime.run_supervision(post_team_room=True)
        self.assertEqual(snapshot, {"action": "RECONCILE"})
        run.assert_called_once()
        self.assertIn("--post-team-room", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
