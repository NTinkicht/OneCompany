#!/usr/bin/env python3
"""Durable GitHub-ledger CASStore tests."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from l5_kernel import Observation, RepoMode, acquire, attach_intent, release, resolve_intent
from l5_ledger_store import DurableLedgerCASStore


def empty_ledger(repo="repo"):
    """Return a valid empty schema-v2 ledger."""
    return {
        "schema_version": 2,
        "repository": repo,
        "revision": 0,
        "mode": "NORMAL",
        "mode_version": 1,
        "human_clear_required": False,
        "leases": {},
        "budgets": {},
        "observations": {},
        "platform_enforcement": {
            "branch_protected": True,
            "active_rulesets": 1,
        },
    }


class FakeBackend:
    """In-memory blob-CAS backend with deterministic SHA identities."""

    def __init__(self, doc):
        self.doc = json.loads(json.dumps(doc))
        self.generation = 1
        self.fail_next = False

    @property
    def sha(self):
        """Return synthetic current blob identity."""
        return f"blob-{self.generation}"

    def read_ledger(self):
        """Return a deep copy and current synthetic blob SHA."""
        return json.loads(json.dumps(self.doc)), self.sha

    def compare_and_swap(self, expected_blob_sha, content):
        """Replace content only when exact current blob identity matches."""
        if self.fail_next:
            self.fail_next = False
            return False
        if expected_blob_sha != self.sha:
            return False
        self.doc = json.loads(content)
        self.generation += 1
        return True


class DurableStoreTests(unittest.TestCase):
    """Cross-run durable CAS behavior."""

    def test_round_trip_acquire_intent_resolve_release(self):
        """Kernel lifecycle persists through the durable adapter."""
        backend = FakeBackend(empty_ledger())
        store = DurableLedgerCASStore("repo", backend)
        obs = Observation("a" * 40, "b" * 40, "wu", "t")

        lease = acquire(store, "repo:item:1:PUSH", "run-1", obs, now_srv=1)
        self.assertIsNotNone(lease)

        intended = attach_intent(
            store,
            lease,
            "repo",
            "1",
            "push",
            now_srv=2,
        )
        self.assertIsNotNone(intended)

        resolved = resolve_intent(store, intended, "DONE")
        self.assertIsNotNone(resolved)

        released = release(store, resolved, now_srv=3)
        self.assertIsNotNone(released)

        row = backend.doc["leases"]["repo:item:1:PUSH"]
        self.assertEqual(row["state"], "RELEASED")
        self.assertEqual(row["intent"]["state"], "DONE")

    def test_release_after_ttl_is_still_a_released_tombstone(self):
        """Late terminal release is explicitly persisted as RELEASED."""
        backend = FakeBackend(empty_ledger())
        store = DurableLedgerCASStore("repo", backend)
        obs = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "k", "run-1", obs, now_srv=1, ttl=5)
        intended = attach_intent(store, lease, "repo", "1", "push", now_srv=2)
        done = resolve_intent(store, intended, "DONE")
        released = release(store, done, now_srv=10)
        self.assertIsNotNone(released)
        self.assertEqual(backend.doc["leases"]["k"]["state"], "RELEASED")

    def test_merge_locked_mode_exit_needs_verified_transition(self):
        """The durable ledger refuses an unverified MERGE_LOCKED exit."""
        doc = empty_ledger()
        doc["mode"] = "MERGE_LOCKED"
        backend = FakeBackend(doc)
        store = DurableLedgerCASStore("repo", backend)
        self.assertFalse(store.cas_repo_mode("repo", 1, RepoMode.NORMAL))
        self.assertTrue(
            store.cas_repo_mode(
                "repo",
                1,
                RepoMode.NORMAL,
                post_merge_verified=True,
            )
        )

    def test_blob_race_rejects_stale_write(self):
        """GitHub blob CAS conflict rejects a stale lease mutation."""
        backend = FakeBackend(empty_ledger())
        store = DurableLedgerCASStore("repo", backend)
        obs = Observation("a" * 40, "b" * 40)

        backend.fail_next = True
        lease = acquire(store, "k", "run-1", obs, now_srv=1)
        self.assertIsNone(lease)
        self.assertEqual(backend.doc["leases"], {})

    def test_tombstone_preserves_epoch_on_reacquire(self):
        """Released records remain and force monotonic next epoch."""
        backend = FakeBackend(empty_ledger())
        store = DurableLedgerCASStore("repo", backend)
        obs = Observation("a" * 40, "b" * 40)

        first = acquire(store, "k", "run-1", obs, now_srv=1, ttl=5)
        intended = attach_intent(store, first, "repo", "1", "push", now_srv=2)
        done = resolve_intent(store, intended, "DONE")
        released = release(store, done, now_srv=3)
        self.assertIsNotNone(released)

        second = acquire(store, "k", "run-2", obs, now_srv=6, ttl=5)
        self.assertIsNotNone(second)
        self.assertEqual(second.epoch, first.epoch + 1)
        self.assertGreater(second.version, released.version)

    def test_human_clear_mode_transition_is_enforced(self):
        """Durable mode cannot leave GOVERNANCE_DRIFT without human clearance."""
        doc = empty_ledger()
        doc["mode"] = "GOVERNANCE_DRIFT"
        doc["human_clear_required"] = True
        backend = FakeBackend(doc)
        store = DurableLedgerCASStore("repo", backend)

        self.assertFalse(store.cas_repo_mode("repo", 1, RepoMode.NORMAL))
        self.assertTrue(
            store.cas_repo_mode(
                "repo",
                1,
                RepoMode.NORMAL,
                human_clear=True,
            )
        )
        self.assertEqual(store.read_repo_mode("repo")[0], RepoMode.NORMAL)

    def test_repo_identity_mismatch_fails_closed(self):
        """A store cannot read another repository's ledger."""
        backend = FakeBackend(empty_ledger("other"))
        store = DurableLedgerCASStore("repo", backend)
        with self.assertRaises(Exception):
            store.read_repo_mode("repo")


if __name__ == "__main__":
    unittest.main()
