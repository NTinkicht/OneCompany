#!/usr/bin/env python3
"""Regression tests for the Claude-exact L5 kernel."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_kernel import *


def merge_snapshot():
    """Build a fully valid merge fixture."""
    head = "a" * 40
    base = "b" * 40
    source = {"app_id": 1, "workflow_path": ".github/workflows/ci.yml"}
    check = {
        "head_sha": head,
        "tested_base_sha": base,
        "latest_attempt": True,
        "conclusion": "success",
        "app_id": 1,
        "workflow_path": ".github/workflows/ci.yml",
        "assertion_failure_any_attempt": False,
        "attempt_history_complete": True,
        "source_verified": True,
    }
    sec_source = {"app_id": 2, "workflow_path": ".github/workflows/security.yml"}
    sec_check = {**check, "app_id": 2, "workflow_path": ".github/workflows/security.yml"}
    review = {
        "state": "APPROVED",
        "commit_id": head,
        "base_sha": base,
        "complete": True,
        "skipped": False,
        "covers_full_diff": True,
        "author": "coderabbitai",
        "material_authors": ["chatgpt"],
        "controller_identities": ["controller-1", "controller-2"],
        "designated_independent": True,
        "reviewer_eligible": True,
        "authorship_complete": True,
        "material_authors_head_sha": head,
        "identity_source_verified": True,
    }
    snap = {
        "head_sha": head,
        "base_sha": base,
        "expected_head_sha": head,
        "expected_base_sha": base,
        "repo_mode": "NORMAL",
        "required_checks": [check],
        "required_check_sources": [source],
        "security_checks": [sec_check],
        "security_check_sources": [sec_source],
        "review": review,
        "ci": "GREEN",
        "independent_review_pass": True,
    }
    for key in TRUE_FIELDS:
        snap[key] = True
    for key in FALSE_FIELDS:
        snap[key] = False
    return snap


class KernelTests(unittest.TestCase):
    """Safety regression suite."""

    def setUp(self):
        self.store = MemoryCASStore()
        self.assertTrue(self.store.cas_repo_mode("repo", None, RepoMode.NORMAL))
        self.obs = Observation("a" * 40, "b" * 40, "wu", "t")

    def test_epoch_intent_recovery_and_release(self):
        """Pending intents block reclaim until explicitly resolved."""
        first = acquire(self.store, "k", "r1", self.obs, now_srv=1, ttl=5)
        self.assertIsNotNone(first)
        with_intent = attach_intent(self.store, first, "repo", "item", "merge", now_srv=2)
        self.assertIsNotNone(with_intent)
        self.assertIsNone(acquire(self.store, "k", "r2", self.obs, now_srv=10))
        self.assertIsNone(release(self.store, with_intent, now_srv=10))
        done = resolve_intent(self.store, with_intent, "ABORTED")
        self.assertIsNotNone(done)
        released = release(self.store, done, now_srv=10)
        self.assertIsNotNone(released)
        second = acquire(self.store, "k", "r2", self.obs, now_srv=11, ttl=5)
        self.assertIsNotNone(second)
        self.assertEqual(second.epoch, first.epoch + 1)

    def test_stale_release_rejected(self):
        """A stale lease snapshot cannot release a newer record."""
        first = acquire(self.store, "k", "r1", self.obs, now_srv=1)
        renewed = renew(self.store, first, now_srv=2)
        self.assertIsNotNone(renewed)
        self.assertIsNone(release(self.store, first, now_srv=3))

    def test_expired_renew_and_intent_rejected(self):
        """Expired leases cannot be renewed or acquire new intent."""
        first = acquire(self.store, "k", "r1", self.obs, now_srv=1, ttl=2)
        self.assertIsNone(renew(self.store, first, now_srv=3))
        self.assertIsNone(attach_intent(self.store, first, "repo", "i", "merge", now_srv=3))

    def test_pending_intent_cannot_be_replaced(self):
        """Only one unresolved write intent may exist per lease."""
        first = acquire(self.store, "k", "r1", self.obs, now_srv=1)
        one = attach_intent(self.store, first, "repo", "i", "merge", now_srv=2)
        self.assertIsNotNone(one)
        self.assertIsNone(attach_intent(self.store, one, "repo", "i", "push", now_srv=3))

    def test_changed_observation_fails_fence(self):
        """Fencing identifies observation drift, not lease expiry."""
        first = acquire(self.store, "k", "r1", self.obs, now_srv=1, ttl=300)
        with_intent = attach_intent(self.store, first, "repo", "i", "merge", now_srv=2)
        self.assertEqual(fence_ok(self.store, "repo", with_intent, self.obs, now_srv=3), (True, "OK"))
        changed = replace(self.obs, pr_updated_at="human-change")
        self.assertEqual(fence_ok(self.store, "repo", with_intent, changed, now_srv=3), (False, "OBSERVATION_CHANGED"))

    def test_human_modes_block_all_automated_writes(self):
        """Human-clear-only modes block even revert effects."""
        for mode in HUMAN_CLEAR_ONLY:
            store = MemoryCASStore()
            store.modes["repo"] = (mode, 1)
            lease = acquire(store, "k", "r1", self.obs, now_srv=1)
            intent = attach_intent(store, lease, "repo", "i", "revert", now_srv=2)
            self.assertFalse(fence_ok(store, "repo", intent, self.obs, now_srv=3)[0])

    def test_main_broken_allows_only_revert(self):
        """MAIN_BROKEN permits narrowly scoped revert recovery."""
        for op in ("revert", "comment", "push"):
            store = MemoryCASStore()
            store.modes["repo"] = (RepoMode.MAIN_BROKEN, 1)
            lease = acquire(store, "k", "r1", self.obs, now_srv=1)
            intent = attach_intent(store, lease, "repo", "i", op, now_srv=2)
            self.assertEqual(fence_ok(store, "repo", intent, self.obs, now_srv=3)[0], op == "revert")

    def test_missing_repo_mode_fails_closed(self):
        """Absent persisted mode is degraded, never NORMAL."""
        self.assertEqual(MemoryCASStore().read_repo_mode("missing")[0], RepoMode.AUTOMATION_DEGRADED)

    def test_human_clear_required_to_exit_protected_mode(self):
        """Protected modes cannot be cleared automatically."""
        store = MemoryCASStore()
        store.modes["repo"] = (RepoMode.GOVERNANCE_DRIFT, 7)
        self.assertFalse(store.cas_repo_mode("repo", 7, RepoMode.NORMAL, human_clear=False))
        self.assertTrue(store.cas_repo_mode("repo", 7, RepoMode.NORMAL, human_clear=True))

    def test_merge_ok_full_predicate(self):
        """A complete valid merge fixture qualifies."""
        self.assertEqual(merge_ok(merge_snapshot()), (True, ()))

    def test_no_rerun_to_green_requires_explicit_false(self):
        """Missing/true attempt-history evidence fails closed."""
        snap = merge_snapshot()
        snap["required_checks"][0].pop("assertion_failure_any_attempt")
        ok, why = merge_ok(snap)
        self.assertFalse(ok)
        self.assertIn("REQUIRED_CHECKS_INVALID", why)
        snap = merge_snapshot()
        snap["required_checks"][0]["assertion_failure_any_attempt"] = True
        ok, why = merge_ok(snap)
        self.assertFalse(ok)
        self.assertIn("REQUIRED_CHECKS_INVALID", why)

    def test_merge_queue_cannot_bypass_tested_base(self):
        """Merge queue status never substitutes for tested-base identity."""
        snap = merge_snapshot()
        snap["required_checks"][0]["merge_queue"] = True
        snap["required_checks"][0]["tested_base_sha"] = "c" * 40
        ok, why = merge_ok(snap)
        self.assertFalse(ok)
        self.assertIn("REQUIRED_CHECKS_INVALID", why)

    def test_check_source_spoof_fails(self):
        """Unpinned app/workflow identity fails closed."""
        snap = merge_snapshot()
        snap["required_checks"][0]["app_id"] = 999
        ok, why = merge_ok(snap)
        self.assertFalse(ok)
        self.assertIn("REQUIRED_CHECKS_INVALID", why)

    def test_review_must_be_external_exact_head(self):
        """Reviewer cannot be a material author/controller."""
        snap = merge_snapshot()
        snap["review"]["author"] = "chatgpt"
        ok, why = merge_ok(snap)
        self.assertFalse(ok)
        self.assertIn("REVIEW_INVALID", why)

    def test_review_authorship_must_be_head_bound(self):
        """Material-author evidence is bound to exact reviewed head."""
        snap = merge_snapshot()
        snap["review"]["material_authors_head_sha"] = "c" * 40
        ok, why = merge_ok(snap)
        self.assertFalse(ok)
        self.assertIn("REVIEW_INVALID", why)

    def test_unknown_gate_fails_closed(self):
        """Missing required merge datum produces its specific failure."""
        snap = merge_snapshot()
        del snap["files_fully_enumerated"]
        ok, why = merge_ok(snap)
        self.assertFalse(ok)
        self.assertIn("FILES_FULLY_ENUMERATED_NOT_TRUE", why)

    def test_budget_parks(self):
        """Exhausted bounded-work budget parks item."""
        self.assertEqual(classify_item({"ci": "GREEN"}, Budget(fix_iterations=MAX_FIX_ITERATIONS)), ItemState.PARKED)

    def test_classifies_human_and_dependency_holds(self):
        """Human and dependency holds have explicit states."""
        self.assertEqual(classify_item({"human_hold": True}, Budget()), ItemState.BLOCK_HUMAN)
        self.assertEqual(classify_item({"dependency_wait": True}, Budget()), ItemState.WAIT_DEPENDENCY)


if __name__ == "__main__":
    unittest.main()
