#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_controller import *
from l5_kernel import *
from test_l5_kernel import merge_snapshot


class Ports:
    def __init__(self, item=None):
        self.item = item or {"item_id": "1", "ci": "PENDING", "head_sha": "a" * 40, "base_sha": "b" * 40}
        self.detect = "UNKNOWN"
        self.outcome = "APPLIED"
        self.health = "UNKNOWN"

    def governance_snapshot(self):
        return {
            "ledger_reachable": True,
            "platform_enforcement_ok": True,
            "live_rules_at_least_pinned": True,
            "rulesets_or_protection_active": True,
            "required_check_sources_pinned": True,
            "controller_admin": False,
            "controller_bypass": False,
        }

    def inventory(self):
        return [self.item]

    def observe_item(self, item_id):
        return dict(self.item)

    def budget_for(self, item_id):
        return Budget()

    def detect_intent(self, intent):
        return self.detect

    def perform(self, operation, item, **kwargs):
        return self.outcome

    def post_merge_health(self, item_id):
        return self.health


class ControllerTests(unittest.TestCase):
    def test_governance_drift_blocks_before_inventory(self):
        class Drift(Ports):
            def governance_snapshot(self):
                snap = super().governance_snapshot()
                snap["platform_enforcement_ok"] = False
                return snap
        result = run_once("repo", MemoryCASStore(), Drift(), now_srv=1)
        self.assertEqual(result.stage, RunStage.REPOSITORY_MODE)
        self.assertEqual(result.status, "BLOCKED")

    def test_unknown_pending_intent_blocks_all_new_work(self):
        store = MemoryCASStore()
        obs = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "k", "old", obs, now_srv=1)
        attach_intent(store, lease, "repo", "old", "merge")
        result = run_once("repo", store, Ports(), now_srv=2)
        self.assertEqual(result.stage, RunStage.INTENT_RECOVERY)
        self.assertEqual(result.status, "BLOCKED")

    def test_applied_pending_intent_is_resolved_before_selection(self):
        store = MemoryCASStore()
        obs = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "k", "old", obs, now_srv=1)
        attach_intent(store, lease, "repo", "old", "merge")
        ports = Ports()
        ports.detect = "APPLIED"
        result = run_once("repo", store, ports, now_srv=2)
        self.assertEqual(store.read("k").intent.state, "DONE")
        self.assertNotEqual(result.stage, RunStage.INTENT_RECOVERY)

    def test_ci_rerun_is_fenced_and_intent_persisted(self):
        item = {"item_id": "1", "ci": "INFRA_FAILED", "head_sha": "a" * 40, "base_sha": "b" * 40}
        store = MemoryCASStore()
        result = run_once("repo", store, Ports(item), now_srv=1)
        self.assertEqual(result.status, "APPLIED")
        rows = [row for row in store.list_leases() if row.intent]
        self.assertEqual(rows[0].intent.state, "DONE")

    def test_merge_recomputes_full_merge_ok(self):
        item = merge_snapshot()
        item["item_id"] = "1"
        store = MemoryCASStore()
        result = run_once("repo", store, Ports(item), now_srv=1)
        self.assertEqual(result.action, "merge")
        self.assertEqual(result.status, "APPLIED")

    def test_merge_unknown_outcome_remains_pending(self):
        item = merge_snapshot()
        item["item_id"] = "1"
        store = MemoryCASStore()
        ports = Ports(item)
        ports.outcome = "UNKNOWN"
        result = run_once("repo", store, ports, now_srv=1)
        self.assertEqual(result.status, "OUTCOME_UNKNOWN")
        pending = [row for row in store.list_leases() if row.intent and row.intent.state == "PENDING"]
        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()
