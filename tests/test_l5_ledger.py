#!/usr/bin/env python3
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_kernel import Intent, Lease, Observation, RepoMode
from l5_ledger import *


def base_doc():
    return {
        "schema_version": 2,
        "repository": "repo",
        "revision": 0,
        "mode": "GOVERNANCE_DRIFT",
        "mode_version": 1,
        "human_clear_required": True,
        "platform_enforcement": {"branch_protected": False, "active_rulesets": 0},
        "leases": {},
        "budgets": {},
        "observations": {},
    }


def lease(version=1, epoch=1, active=True, intent=None, holder="run-a"):
    return Lease(
        key="k",
        holder=holder,
        epoch=epoch,
        observed=Observation("a" * 40, "b" * 40),
        acquired_at=1,
        expires_at=10,
        version=version,
        intent=intent,
        active=active,
    )


class Backend:
    def __init__(self, doc):
        self.doc = copy.deepcopy(doc)
        self.sha = "sha-1"

    def read(self):
        return copy.deepcopy(self.doc), self.sha

    def write(self, document, expected_blob_sha):
        if expected_blob_sha != self.sha:
            raise LedgerConflict("BLOB_STALE")
        self.doc = copy.deepcopy(document)
        self.sha = "sha-" + str(int(self.sha.split("-")[1]) + 1)
        return self.sha


class LedgerTests(unittest.TestCase):
    def test_validate_v2(self):
        validate_ledger(base_doc(), expected_repo="repo")

    def test_human_clear_required(self):
        doc = base_doc()
        with self.assertRaises(LedgerConflict):
            cas_mode(doc, expected_revision=0, expected_mode_version=1, new_mode=RepoMode.NORMAL)

    def test_pending_intent_cannot_disappear(self):
        doc = base_doc()
        pending = Intent("op", "i", "merge", "a" * 40, "b" * 40, 1)
        row1 = lease(intent=pending)
        doc1 = cas_lease(doc, "k", expected_revision=0, expected_lease_version=None, new_record=lease_to_record(row1))
        row2 = lease(version=2, epoch=1, intent=None)
        with self.assertRaises(LedgerInvalid):
            cas_lease(doc1, "k", expected_revision=1, expected_lease_version=1, new_record=lease_to_record(row2))

    def test_tombstone_preserves_epoch_floor(self):
        doc = base_doc()
        row1 = lease()
        doc1 = cas_lease(doc, "k", expected_revision=0, expected_lease_version=None, new_record=lease_to_record(row1))
        retired = lease(version=2, active=False)
        doc2 = cas_lease(doc1, "k", expected_revision=1, expected_lease_version=1, new_record=lease_to_record(retired))
        stale_reactivate = lease(version=3, epoch=1, active=True, holder="run-b")
        with self.assertRaises(LedgerInvalid):
            cas_lease(doc2, "k", expected_revision=2, expected_lease_version=2, new_record=lease_to_record(stale_reactivate))
        fresh = lease(version=3, epoch=2, active=True, holder="run-b")
        doc3 = cas_lease(doc2, "k", expected_revision=2, expected_lease_version=2, new_record=lease_to_record(fresh))
        self.assertEqual(doc3["leases"]["k"]["epoch"], 2)

    def test_ledger_store_uses_blob_and_record_cas(self):
        backend = Backend(base_doc())
        store = LedgerCASStore(backend, "repo")
        first = lease()
        self.assertTrue(store.cas("k", None, first))
        self.assertEqual(store.read("k"), first)
        stale = lease(version=2, epoch=1, holder="run-b")
        with self.assertRaises(LedgerInvalid):
            store.cas("k", 1, stale)


if __name__ == "__main__":
    unittest.main()
