#!/usr/bin/env python3
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_kernel import *


def merge_snapshot():
    h = "a" * 40
    b = "b" * 40
    src = {"app_id": 1, "workflow_path": ".github/workflows/ci.yml"}
    secsrc = {"app_id": 2, "workflow_path": ".github/workflows/security.yml"}
    check = {
        **src,
        "head_sha": h,
        "tested_base_sha": b,
        "latest_attempt": True,
        "conclusion": "success",
        "assertion_history_complete": True,
        "assertion_failure_any_attempt": False,
    }
    seccheck = {
        **secsrc,
        "head_sha": h,
        "tested_base_sha": b,
        "latest_attempt": True,
        "conclusion": "success",
        "assertion_history_complete": True,
        "assertion_failure_any_attempt": False,
    }
    review = {
        "state": "APPROVED",
        "commit_id": h,
        "base_sha": b,
        "complete": True,
        "skipped": False,
        "covers_full_diff": True,
        "author": "coderabbitai",
        "material_authors": ["chatgpt"],
        "controller_identities": ["controller-1"],
        "designated_independent": True,
    }
    snapshot = {
        "head_sha": h,
        "base_sha": b,
        "expected_head_sha": h,
        "expected_base_sha": b,
        "repo_mode": "NORMAL",
        "required_checks": [check],
        "security_checks": [seccheck],
        "required_check_sources": [src],
        "security_check_sources": [secsrc],
        "review": review,
        "ci": "GREEN",
        "independent_review_pass": True,
    }
    for key in TRUE_FIELDS:
        snapshot[key] = True
    for key in FALSE_FIELDS:
        snapshot[key] = False
    return snapshot


class KernelTests(unittest.TestCase):
    def test_monotonic_epoch_and_pending_intent_blocks_reclaim(self):
        store = MemoryCASStore()
        observed = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "k", "r1", observed, now_srv=1, ttl=5)
        intended = attach_intent(store, lease, "repo", "item", "merge")
        self.assertIsNone(acquire(store, "k", "r2", observed, now_srv=10, ttl=5))
        resolved = resolve_intent(store, intended, "ABORTED")
        retired = release(store, resolved, now_srv=10)
        lease2 = acquire(store, "k", "r2", observed, now_srv=11, ttl=5)
        self.assertEqual(lease2.epoch, retired.epoch + 1)
        self.assertGreater(lease2.version, retired.version)

    def test_stale_release_cannot_finalize_newer_intent(self):
        store = MemoryCASStore()
        observed = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "k", "r1", observed, now_srv=1)
        intended = attach_intent(store, lease, "repo", "item", "merge")
        self.assertIsNone(release(store, lease, now_srv=2))
        self.assertIsNone(release(store, intended, now_srv=2))
        self.assertEqual(store.read("k").intent.state, "PENDING")

    def test_pending_intent_cannot_be_replaced(self):
        store = MemoryCASStore()
        observed = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "k", "r1", observed, now_srv=1)
        intended = attach_intent(store, lease, "repo", "item", "merge")
        self.assertIsNone(attach_intent(store, intended, "repo", "item", "push"))
        self.assertEqual(store.read("k").intent.op_id, intended.intent.op_id)

    def test_changed_observation_fails_fence(self):
        store = MemoryCASStore()
        observed = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "k", "r1", observed, now_srv=1)
        intended = attach_intent(store, lease, "repo", "item", "merge")
        self.assertFalse(fence_ok(store, "repo", intended, replace(observed, head="c" * 40), now_srv=2)[0])

    def test_revert_requires_narrow_emergency_authority(self):
        store = MemoryCASStore()
        observed = Observation("a" * 40, "b" * 40)
        store.cas_repo_mode("repo", None, RepoMode.HALTED)
        lease = acquire(store, "k", "r1", observed, now_srv=1)
        intended = attach_intent(store, lease, "repo", "item", "revert")
        self.assertFalse(fence_ok(store, "repo", intended, observed, now_srv=2, emergency_revert_authorized=True)[0])
        store.modes["repo"] = (RepoMode.MAIN_BROKEN, 2)
        self.assertTrue(fence_ok(store, "repo", intended, observed, now_srv=2, emergency_revert_authorized=True)[0])

    def test_ambiguous_write_requires_readback(self):
        store = MemoryCASStore()
        observed = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "k", "r1", observed, now_srv=1)
        intended = attach_intent(store, lease, "repo", "item", "merge")
        self.assertEqual(intent_recovery(intended, "UNKNOWN"), "READBACK_REQUIRED")

    def test_capacity_and_merge_locks_unique(self):
        for key in (repo_merge_lock_key("repo"), capacity_slot_key("repo", 4)):
            store = MemoryCASStore()
            observed = Observation("a" * 40, "b" * 40)
            self.assertEqual(sum(acquire(store, key, f"r{i}", observed, now_srv=1) is not None for i in range(4)), 1)

    def test_unprotected_is_governance_drift(self):
        self.assertEqual(
            governance_mode({
                "ledger_reachable": True,
                "platform_enforcement_ok": False,
                "live_rules_at_least_pinned": True,
                "rulesets_or_protection_active": False,
                "required_check_sources_pinned": True,
            }),
            RepoMode.GOVERNANCE_DRIFT,
        )

    def test_missing_ledger_evidence_degrades_automation(self):
        self.assertEqual(governance_mode({}), RepoMode.AUTOMATION_DEGRADED)

    def test_merge_ok_full_predicate(self):
        self.assertEqual(merge_ok(merge_snapshot()), (True, ()))

    def test_missing_assertion_history_fails_closed(self):
        snapshot = merge_snapshot()
        del snapshot["required_checks"][0]["assertion_history_complete"]
        self.assertFalse(merge_ok(snapshot)[0])

    def test_rerun_to_green_fails(self):
        snapshot = merge_snapshot()
        snapshot["required_checks"][0]["assertion_failure_any_attempt"] = True
        self.assertFalse(merge_ok(snapshot)[0])

    def test_merge_queue_mismatched_base_fails(self):
        snapshot = merge_snapshot()
        snapshot["required_checks"][0]["tested_base_sha"] = "c" * 40
        snapshot["required_checks"][0]["merge_queue"] = True
        self.assertFalse(merge_ok(snapshot)[0])

    def test_check_source_spoof_fails(self):
        snapshot = merge_snapshot()
        snapshot["required_checks"][0]["app_id"] = 999
        self.assertFalse(merge_ok(snapshot)[0])

    def test_review_must_be_external_exact_head(self):
        snapshot = merge_snapshot()
        snapshot["review"]["author"] = "chatgpt"
        self.assertFalse(merge_ok(snapshot)[0])
        snapshot = merge_snapshot()
        snapshot["review"]["commit_id"] = "c" * 40
        self.assertFalse(merge_ok(snapshot)[0])

    def test_unknown_gate_fails_closed(self):
        snapshot = merge_snapshot()
        del snapshot["files_fully_enumerated"]
        self.assertFalse(merge_ok(snapshot)[0])

    def test_budget_parks_and_idle_quiesces(self):
        self.assertEqual(classify_item({"ci": "GREEN"}, Budget(fix_iterations=MAX_FIX_ITERATIONS)), ItemState.PARKED)
        self.assertEqual(classify_item({"no_actionable_work": True}, Budget()), ItemState.IDLE)


if __name__ == "__main__":
    unittest.main()
