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
        "main_broken": False,
        "main_broken_env": False,
        "automation_degraded": False,
        "provider_throttled": False,
        "merge_locked": False,
        "archived_or_permission_lost": False,
    }
    row.update(overrides)
    return row


def merge_item():
    """Return a fully valid merge-eligible item."""
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
    item = {
        "item_id": "7",
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
        item[key] = True
    for key in FALSE_FIELDS:
        item[key] = False
    return item


class FakeIO:
    """Deterministic trusted structured IO double."""

    def __init__(self, repo=None, items=None):
        self.repo = repo or repo_snapshot()
        self.items = list(items or [])
        self.pending = []
        self.detections = {}
        self.executed = []
        self.result = {"status": "COMPLETE", "reason": "EFFECT_VERIFIED"}
        self.health = "HEALTHY"
        self.refresh_queue = []
        self.clock = 1.0

    def repo_snapshot(self):
        """Return current governance evidence."""
        return dict(self.repo)

    def pending_intent_leases(self):
        """Return unresolved durable intents known to the invocation."""
        return list(self.pending)

    def detect_intent_effect(self, lease):
        """Return trusted effect readback for one pending intent."""
        return self.detections.get(lease.key, "UNKNOWN")

    def inventory(self):
        """Return current item inventory."""
        return [dict(item) for item in self.items]

    def refresh_item(self, item):
        """Return a fresh exact item snapshot."""
        if self.refresh_queue:
            return dict(self.refresh_queue.pop(0))
        return dict(item)

    def budget_for(self, item):
        """Return an unexhausted test budget."""
        return Budget()

    def observe_item(self, item):
        """Derive resource identity from item evidence."""
        return Observation(
            item.get("head_sha", "a" * 40),
            item.get("base_sha", "b" * 40),
            str(item.get("wu_body_hash", "")),
            str(item.get("pr_updated_at", "")),
        )

    def trusted_now(self):
        """Return monotonically increasing trusted/server time."""
        value = self.clock
        self.clock += 1.0
        return value

    def post_merge_health(self, item):
        """Return trusted main-health classification."""
        return self.health

    def execute_guarded(self, operation, item, lease):
        """Record one guarded effect and return configured result."""
        self.executed.append((operation, str(item["item_id"]), lease.intent.idem_key))
        return dict(self.result)


class ControllerTests(unittest.TestCase):
    """Controller orchestration, recovery, and merge-lock tests."""

    def test_governance_drift_blocks_before_inventory(self):
        """Live governance drift is persisted and blocks action."""
        store = MemoryCASStore()
        io = FakeIO(repo_snapshot(rulesets_or_protection_active=False))
        result = run_once("repo", io, store, now_srv=1)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "GOVERNANCE_DRIFT")
        self.assertEqual(io.executed, [])
        self.assertEqual(store.read_repo_mode("repo")[0], RepoMode.GOVERNANCE_DRIFT)

    def test_human_mode_cannot_be_auto_cleared(self):
        """A protected mode requires explicit human clearance."""
        store = MemoryCASStore()
        store.modes["repo"] = (RepoMode.GOVERNANCE_DRIFT, 4)
        result = run_once("repo", FakeIO(repo_snapshot()), store, now_srv=1)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "HUMAN_CLEAR_REQUIRED")

    def test_ci_infra_path_executes_one_guarded_action(self):
        """A bounded infra retry performs exactly one guarded action."""
        item = {
            "item_id": "7",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "ci": "INFRA_FAILED",
        }
        io = FakeIO(items=[item])
        result = run_once("repo", io, MemoryCASStore(), now_srv=1)
        self.assertEqual(result.status, "COMPLETE")
        self.assertEqual(result.action, "retry_ci")
        self.assertEqual(len(io.executed), 1)

    def test_unknown_write_stays_pending_for_next_run(self):
        """An unknown result remains PENDING for next-run readback."""
        item = {
            "item_id": "7",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "ci": "INFRA_FAILED",
        }
        io = FakeIO(items=[item])
        io.result = {"status": "IN_PROGRESS", "reason": "EFFECT_NOT_YET_VERIFIED"}
        store = MemoryCASStore()
        result = run_once("repo", io, store, now_srv=1)
        self.assertEqual(result.status, "WAIT")
        self.assertEqual(result.reason, "OUTCOME_UNKNOWN")
        pending = [
            lease
            for lease in store.leases.values()
            if lease.intent and lease.intent.state == "PENDING"
        ]
        self.assertEqual(len(pending), 1)

    def test_replay_pending_is_not_marked_done(self):
        """A token reservation replay remains unresolved."""
        item = {
            "item_id": "7",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "ci": "INFRA_FAILED",
        }
        io = FakeIO(items=[item])
        io.result = {"status": "REPLAY_NOOP", "reason": "TOKEN_ALREADY_PERSISTED"}
        store = MemoryCASStore()
        result = run_once("repo", io, store)
        self.assertEqual(result.status, "WAIT")
        self.assertEqual(result.reason, "OUTCOME_UNKNOWN")
        pending = [
            lease
            for lease in store.leases.values()
            if lease.intent and lease.intent.state == "PENDING"
        ]
        self.assertEqual(len(pending), 1)

    def test_replay_already_complete_is_terminal(self):
        """A verified completed replay may resolve and release."""
        item = {
            "item_id": "7",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "ci": "INFRA_FAILED",
        }
        io = FakeIO(items=[item])
        io.result = {"status": "REPLAY_NOOP", "reason": "ALREADY_COMPLETE"}
        store = MemoryCASStore()
        result = run_once("repo", io, store)
        self.assertEqual(result.status, "COMPLETE")
        lease = next(iter(store.leases.values()))
        self.assertEqual(lease.intent.state, "DONE")

    def test_orphan_intent_readback_blocks_new_selection(self):
        """Unknown orphan outcome blocks all new selection."""
        store = MemoryCASStore()
        store.cas_repo_mode("repo", None, RepoMode.NORMAL)
        obs = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "repo:item:1:PUSH", "old", obs, now_srv=0, ttl=300)
        with_intent = attach_intent(store, lease, "repo", "1", "push", now_srv=1)
        io = FakeIO(
            items=[
                {
                    "item_id": "9",
                    "head_sha": "a" * 40,
                    "base_sha": "b" * 40,
                    "ci": "INFRA_FAILED",
                }
            ]
        )
        io.pending = [with_intent]
        io.detections[with_intent.key] = "UNKNOWN"
        result = run_once("repo", io, store, now_srv=2)
        self.assertEqual(result.phase, RunPhase.INTENT_RECOVERY)
        self.assertEqual(result.reason, "RECOVERY_READBACK_REQUIRED")
        self.assertEqual(io.executed, [])

    def test_observation_changes_before_intent(self):
        """A refreshed resource change prevents intent creation."""
        item = {
            "item_id": "7",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "ci": "INFRA_FAILED",
        }
        changed = dict(item)
        changed["pr_updated_at"] = "changed"
        io = FakeIO(items=[item])
        io.refresh_queue = [changed]
        result = run_once("repo", io, MemoryCASStore())
        self.assertEqual(result.reason, "OBSERVATION_CHANGED")
        self.assertEqual(io.executed, [])

    def test_fresh_merge_predicate_rechecked_before_write(self):
        """A merge becomes blocked when fresh evidence loses eligibility."""
        item = merge_item()
        invalid = merge_item()
        invalid["review"]["state"] = "CHANGES_REQUESTED"
        io = FakeIO(items=[item])
        io.refresh_queue = [item, invalid]
        result = run_once("repo", io, MemoryCASStore())
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "MERGE_OK_FALSE_FINAL")
        self.assertEqual(io.executed, [])

    def test_slow_run_fails_final_lease_margin(self):
        """Fresh trusted time prevents a slow invocation from writing."""
        item = {
            "item_id": "7",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "ci": "INFRA_FAILED",
        }

        class SlowIO(FakeIO):
            def __init__(self, items):
                super().__init__(items=items)
                self.times = iter([1.0, 2.0, 299.0])

            def trusted_now(self):
                return next(self.times)

        io = SlowIO([item])
        result = run_once("repo", io, MemoryCASStore())
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "LEASE_TOO_CLOSE_TO_EXPIRY")
        self.assertEqual(io.executed, [])

    def test_merge_stays_locked_until_post_merge_verification(self):
        """A completed merge enters durable MERGE_LOCKED state."""
        item = merge_item()
        io = FakeIO(items=[item])
        store = MemoryCASStore()
        first = run_once("repo", io, store)
        self.assertEqual(first.status, "WAIT")
        self.assertEqual(first.reason, "MERGED_UNVERIFIED")
        self.assertEqual(store.read_repo_mode("repo")[0], RepoMode.MERGE_LOCKED)
        lock = store.read(repo_merge_lock_key("repo"))
        self.assertIsNotNone(lock)
        self.assertEqual(lock.intent.state, "DONE")

        io.items = [
            {
                "item_id": "7",
                "head_sha": "c" * 40,
                "base_sha": "b" * 40,
                "merged": True,
                "post_merge_verified": False,
            }
        ]
        second = run_once("repo", io, store)
        self.assertEqual(second.status, "COMPLETE")
        self.assertEqual(second.reason, "POST_MERGE_VERIFIED")
        self.assertEqual(store.read_repo_mode("repo")[0], RepoMode.NORMAL)

    def test_post_merge_unknown_keeps_lock(self):
        """Unknown main health keeps repository merge-locked."""
        item = merge_item()
        io = FakeIO(items=[item])
        store = MemoryCASStore()
        first = run_once("repo", io, store)
        self.assertEqual(first.reason, "MERGED_UNVERIFIED")
        io.items = [
            {
                "item_id": "7",
                "head_sha": "c" * 40,
                "base_sha": "b" * 40,
                "merged": True,
                "post_merge_verified": False,
            }
        ]
        io.health = "UNKNOWN"
        second = run_once("repo", io, store)
        self.assertEqual(second.status, "WAIT")
        self.assertEqual(second.reason, "POST_MERGE_HEALTH_UNKNOWN")
        self.assertEqual(store.read_repo_mode("repo")[0], RepoMode.MERGE_LOCKED)

    def test_post_merge_broken_transitions_to_main_broken(self):
        """A verified regression transitions to MAIN_BROKEN."""
        item = merge_item()
        io = FakeIO(items=[item])
        store = MemoryCASStore()
        run_once("repo", io, store)
        io.items = [
            {
                "item_id": "7",
                "head_sha": "c" * 40,
                "base_sha": "b" * 40,
                "merged": True,
                "post_merge_verified": False,
            }
        ]
        io.health = "BROKEN"
        result = run_once("repo", io, store)
        self.assertEqual(result.reason, "MAIN_BROKEN")
        self.assertEqual(store.read_repo_mode("repo")[0], RepoMode.MAIN_BROKEN)

    def test_deterministic_selection_prefers_repair_over_review(self):
        """Deterministic remediation has higher priority than review dispatch."""
        repair = {
            "item_id": "9",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "ci": "DETERMINISTIC_FAILED",
        }
        review = {
            "item_id": "1",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "ci": "GREEN",
            "independent_review_pass": False,
        }
        io = FakeIO(items=[review, repair])
        result = run_once("repo", io, MemoryCASStore())
        self.assertEqual(result.item_id, "9")
        self.assertEqual(result.action, "remediate_review")


if __name__ == "__main__":
    unittest.main()
