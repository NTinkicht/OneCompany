#!/usr/bin/env python3
"""Regression tests for the durable Claude L5 ledger."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_kernel import RepoMode
from l5_ledger import *


def base_doc():
    """Return a valid empty ledger."""
    return {
        "schema_version": SCHEMA_VERSION,
        "repository": "NTinkicht/repo",
        "revision": 0,
        "mode": "GOVERNANCE_DRIFT",
        "mode_version": 1,
        "human_clear_required": True,
        "leases": {},
        "budgets": {},
        "observations": {},
        "platform_enforcement": {"branch_protected": False, "active_rulesets": 0},
    }


def lease_row(*, version=1, epoch=1, holder="r1", state="ACTIVE", intent=None):
    """Return a valid persisted lease row."""
    return {
        "version": version,
        "epoch": epoch,
        "holder": holder,
        "state": state,
        "acquired_at": 1.0,
        "expires_at": 300.0 if state == "ACTIVE" else 2.0,
        "observed": {
            "head": "a" * 40,
            "base": "b" * 40,
            "wu_body_hash": "wu",
            "pr_updated_at": "t",
        },
        "intent": intent,
    }


def pending_intent(epoch=1, op_id="op1"):
    """Return a valid PENDING persisted intent."""
    return {
        "op_id": op_id,
        "idem_key": "f" * 64,
        "operation": "merge",
        "expected_head": "a" * 40,
        "expected_base": "b" * 40,
        "epoch": epoch,
        "state": "PENDING",
    }


class LedgerTests(unittest.TestCase):
    """Durable monotonicity and recovery tests."""

    def test_valid_empty_ledger(self):
        """Accept the minimal valid schema-v2 repository ledger."""
        validate_ledger(base_doc())

    def test_human_clear_required_for_protected_mode_exit(self):
        """Require explicit human clearance before leaving protected freeze modes."""
        doc = base_doc()
        with self.assertRaises(LedgerConflict):
            cas_mode(doc, expected_revision=0, expected_mode_version=1, new_mode=RepoMode.NORMAL, human_clear=False)
        out = cas_mode(doc, expected_revision=0, expected_mode_version=1, new_mode=RepoMode.NORMAL, human_clear=True)
        self.assertEqual(out["mode"], "NORMAL")

    def test_lease_delete_forbidden(self):
        """Forbid lease deletion so epoch and version history remain durable."""
        doc = base_doc()
        doc["leases"]["k"] = lease_row()
        with self.assertRaises(LedgerInvalid):
            cas_lease(doc, "k", expected_revision=0, expected_lease_version=1, new_record=None)

    def test_release_tombstone_preserves_epoch_version(self):
        """Preserve fencing epoch and advance version when a lease is released."""
        doc = base_doc()
        doc["leases"]["k"] = lease_row(version=3, epoch=7)
        released = lease_row(version=4, epoch=7, holder="r1", state="RELEASED")
        out = cas_lease(doc, "k", expected_revision=0, expected_lease_version=3, new_record=released)
        self.assertEqual(out["leases"]["k"]["epoch"], 7)
        self.assertEqual(out["leases"]["k"]["version"], 4)
        self.assertEqual(out["leases"]["k"]["state"], "RELEASED")

    def test_new_holder_requires_higher_epoch(self):
        """Require a strictly higher fencing epoch when ownership changes."""
        doc = base_doc()
        doc["leases"]["k"] = lease_row(version=3, epoch=7, holder="r1", state="RELEASED")
        bad = lease_row(version=4, epoch=7, holder="r2")
        with self.assertRaises(LedgerInvalid):
            cas_lease(doc, "k", expected_revision=0, expected_lease_version=3, new_record=bad)
        good = lease_row(version=4, epoch=8, holder="r2")
        out = cas_lease(doc, "k", expected_revision=0, expected_lease_version=3, new_record=good)
        self.assertEqual(out["leases"]["k"]["epoch"], 8)

    def test_active_lease_cannot_be_taken_over_before_expiry(self):
        """Reject durable ownership takeover until the current active lease expires."""
        doc = base_doc()
        doc["leases"]["k"] = lease_row(version=3, epoch=7, holder="r1")
        early = lease_row(version=4, epoch=8, holder="r2")
        early["acquired_at"] = 299.0
        early["expires_at"] = 599.0
        with self.assertRaises(LedgerConflict):
            cas_lease(doc, "k", expected_revision=0, expected_lease_version=3, new_record=early)
        after_expiry = lease_row(version=4, epoch=8, holder="r2")
        after_expiry["acquired_at"] = 300.0
        after_expiry["expires_at"] = 600.0
        out = cas_lease(doc, "k", expected_revision=0, expected_lease_version=3, new_record=after_expiry)
        self.assertEqual(out["leases"]["k"]["holder"], "r2")
        self.assertEqual(out["leases"]["k"]["epoch"], 8)

    def test_pending_intent_cannot_be_lost_replaced_or_reassigned(self):
        """Keep every unresolved PENDING intent immutable and owner-bound."""
        doc = base_doc()
        doc["leases"]["k"] = lease_row(intent=pending_intent())
        with self.assertRaises(LedgerConflict):
            cas_lease(doc, "k", expected_revision=0, expected_lease_version=1, new_record=lease_row(version=2))
        replaced = lease_row(version=2, intent=pending_intent(op_id="different"))
        with self.assertRaises(LedgerConflict):
            cas_lease(doc, "k", expected_revision=0, expected_lease_version=1, new_record=replaced)
        reassigned = lease_row(version=2, epoch=2, holder="r2", intent={**pending_intent(epoch=2), "op_id": "op1"})
        with self.assertRaises(LedgerConflict):
            cas_lease(doc, "k", expected_revision=0, expected_lease_version=1, new_record=reassigned)

    def test_pending_intent_may_resolve_then_release(self):
        """Allow release only after a pending write-ahead intent becomes terminal."""
        doc = base_doc()
        doc["leases"]["k"] = lease_row(intent=pending_intent())
        done = pending_intent(); done["state"] = "DONE"
        resolved = lease_row(version=2, intent=done)
        out = cas_lease(doc, "k", expected_revision=0, expected_lease_version=1, new_record=resolved)
        released = {**resolved, "version": 3, "state": "RELEASED", "expires_at": 2.0}
        out2 = cas_lease(out, "k", expected_revision=1, expected_lease_version=2, new_record=released)
        self.assertEqual(out2["leases"]["k"]["state"], "RELEASED")

    def test_blob_cas_and_revision_cas(self):
        """Reject stale document revisions while validating outer blob CAS evidence."""
        self.assertTrue(blob_cas_ok("abc", "abc"))
        self.assertFalse(blob_cas_ok("abc", "def"))
        with self.assertRaises(LedgerConflict):
            cas_budget(
                base_doc(),
                "item",
                expected_revision=1,
                expected_budget_version=None,
                new_record={"version": 1, "ci_reruns": 0, "fix_iterations": 0, "review_rounds": 0, "lease_acquisitions": 0},
            )


if __name__ == "__main__":
    unittest.main()
