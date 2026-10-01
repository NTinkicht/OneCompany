#!/usr/bin/env python3
"""Executable BOOT-to-ACTION controller tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_controller import *
from l5_kernel import *


def repo_snapshot(**overrides):
    """Return healthy governance evidence."""
    row = {
        "halted": False,
        "controller_integrity_failure": False,
        "security_integrity_failure": False,
        "ledger_reachable": True,
        "platform_enforcement_ok": True,
        "live_rules_at_least_pinned": True,
        "rulesets_or_protection_active": True,
        "required_check_sources_pinned": True,
        "controller_admin": False,
        "controller_bypass": False,
    }
    row.update(overrides)
    return row


class FakeIO:
    """Deterministic structured IO double."""

    def __init__(self, repo=None, items=None):
        self.repo = repo or repo_snapshot()
        self.items = list(items or [])
        self.pending = []
        self.detections = {}
        self.executed = []
        self.result = {"status": "COMPLETE"}

    def repo_snapshot(self): return dict(self.repo)
    def pending_intent_leases(self): return list(self.pending)
    def detect_intent_effect(self, lease): return self.detections.get(lease.key, "UNKNOWN")
    def inventory(self): return list(self.items)
    def budget_for(self, item): return Budget()
    def observe_item(self, item): return Observation(item.get("head_sha", "a" * 40), item.get("base_sha", "b" * 40))
    def execute_guarded(self, operation, item, lease):
        self.executed.append((operation, str(item["item_id"]), lease.intent.idem_key))
        return dict(self.result)


class ControllerTests(unittest.TestCase):
    """Controller orchestration and recovery tests."""

    def test_governance_drift_blocks_before_inventory(self):
        store = MemoryCASStore()
        io = FakeIO(repo_snapshot(rulesets_or_protection_active=False))
        result = run_once("repo", io, store, now_srv=1)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "GOVERNANCE_DRIFT")
        self.assertEqual(io.executed, [])

    def test_human_mode_cannot_be_auto_cleared(self):
        store = MemoryCASStore()
        store.modes["repo"] = (RepoMode.GOVERNANCE_DRIFT, 4)
        result = run_once("repo", FakeIO(repo_snapshot()), store, now_srv=1)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "HUMAN_CLEAR_REQUIRED")

    def test_ci_infra_path_executes_one_guarded_action(self):
        item = {"item_id": "7", "head_sha": "a" * 40, "base_sha": "b" * 40, "ci": "INFRA_FAILED"}
        io = FakeIO(items=[item])
        result = run_once("repo", io, MemoryCASStore(), now_srv=1)
        self.assertEqual(result.status, "COMPLETE")
        self.assertEqual(result.action, "retry_ci")
        self.assertEqual(len(io.executed), 1)

    def test_unknown_write_stays_pending_for_next_run(self):
        item = {"item_id": "7", "head_sha": "a" * 40, "base_sha": "b" * 40, "ci": "INFRA_FAILED"}
        io = FakeIO(items=[item]); io.result = {"status": "IN_PROGRESS"}
        store = MemoryCASStore()
        result = run_once("repo", io, store, now_srv=1)
        self.assertEqual(result.status, "WAIT")
        self.assertEqual(result.reason, "OUTCOME_UNKNOWN")
        pending = [x for x in store.leases.values() if x.intent and x.intent.state == "PENDING"]
        self.assertEqual(len(pending), 1)

    def test_orphan_intent_readback_blocks_new_selection(self):
        store = MemoryCASStore(); store.cas_repo_mode("repo", None, RepoMode.NORMAL)
        obs = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "repo:item:1:PUSH", "old", obs, now_srv=0, ttl=300)
        with_intent = attach_intent(store, lease, "repo", "1", "push", now_srv=1)
        io = FakeIO(items=[{"item_id": "9", "head_sha": "a" * 40, "base_sha": "b" * 40, "ci": "INFRA_FAILED"}])
        io.pending = [with_intent]; io.detections[with_intent.key] = "UNKNOWN"
        result = run_once("repo", io, store, now_srv=2)
        self.assertEqual(result.phase, RunPhase.INTENT_RECOVERY)
        self.assertEqual(result.reason, "RECOVERY_READBACK_REQUIRED")
        self.assertEqual(io.executed, [])

    def test_orphan_intent_applied_resolves_before_work(self):
        store = MemoryCASStore(); store.cas_repo_mode("repo", None, RepoMode.NORMAL)
        obs = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "repo:item:1:PUSH", "old", obs, now_srv=0, ttl=300)
        with_intent = attach_intent(store, lease, "repo", "1", "push", now_srv=1)
        io = FakeIO(items=[]); io.pending = [with_intent]; io.detections[with_intent.key] = "APPLIED"
        result = run_once("repo", io, store, now_srv=2)
        self.assertEqual(result.status, "IDLE")
        self.assertEqual(store.read(with_intent.key).intent.state, "DONE")

    def test_observation_changes_between_acquire_and_intent(self):
        class FlapIO(FakeIO):
            def __init__(self, items): super().__init__(items=items); self.calls = 0
            def observe_item(self, item):
                self.calls += 1
                return Observation(item["head_sha"], item["base_sha"], pr_updated_at="a" if self.calls == 1 else "b")
        item = {"item_id": "7", "head_sha": "a" * 40, "base_sha": "b" * 40, "ci": "INFRA_FAILED"}
        io = FlapIO([item])
        result = run_once("repo", io, MemoryCASStore(), now_srv=1)
        self.assertEqual(result.reason, "OBSERVATION_CHANGED")
        self.assertEqual(io.executed, [])

    def test_deterministic_selection_prefers_repair_over_review(self):
        repair = {"item_id": "9", "head_sha": "a" * 40, "base_sha": "b" * 40, "ci": "DETERMINISTIC_FAILED"}
        review = {"item_id": "1", "head_sha": "a" * 40, "base_sha": "b" * 40, "ci": "GREEN", "independent_review_pass": False}
        io = FakeIO(items=[review, repair])
        result = run_once("repo", io, MemoryCASStore(), now_srv=1)
        self.assertEqual(result.item_id, "9")
        self.assertEqual(result.action, "remediate_review")


if __name__ == "__main__":
    unittest.main()
