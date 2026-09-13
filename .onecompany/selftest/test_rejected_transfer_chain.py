from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger_lib import derive


def event(i: int, kind: str, actor: str, payload: dict) -> dict:
    return {
        "version": 1,
        "event_id": f"e{i}",
        "type": kind,
        "actor": actor,
        "payload": payload,
        "github_created_at": f"2026-01-01T00:00:{i:02d}Z",
        "github_comment_id": i,
    }


def snapshot() -> dict:
    return {
        "write_scope": ["src/a/**"],
        "resource_locks": [],
        "parallelism": "auto",
        "risk_class": "LOW",
        "dependencies": [],
        "dependency_closure": [],
    }


class RejectedTransferChainTests(unittest.TestCase):
    def test_rejected_transfer_replacement_id_remains_known(self):
        base = {
            "role": "implementation",
            "work_unit": "WU-A",
            "branch": "wu-a",
            "pr": 1,
            "planning_snapshot": snapshot(),
        }
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "worker-a", {**base, "lease_id": "L1", "start_head": "a" * 40}),
            event(2, "ROLE_LEASE_TRANSFERRED", "worker-b", {
                **base,
                "lease_id": "L2",
                "old_lease_id": "L1",
                "new_lease_id": "L2",
                "start_head": "b" * 40,
            }),
            event(3, "ROLE_LEASE_TRANSFERRED", "worker-c", {
                **base,
                "lease_id": "L3",
                "old_lease_id": "L1",
                "new_lease_id": "L3",
                "start_head": "c" * 40,
            }),
            event(4, "ROLE_LEASE_TRANSFERRED", "worker-d", {
                **base,
                "lease_id": "L4",
                "old_lease_id": "L3",
                "new_lease_id": "L4",
                "start_head": "d" * 40,
            }),
        ]
        result = derive(events)

        self.assertEqual([item["id"] for item in result["active_leases"]], ["L2"])
        self.assertEqual(result["integrity_conflicts"], [])
        rejected_ids = [item["rejected_lease_id"] for item in result["rejected_claims"]]
        self.assertEqual(rejected_ids, ["L3", "L4"])
        reasons = [item["violations"][0]["reason"] for item in result["rejected_claims"]]
        self.assertEqual(reasons, ["transfer_source_no_longer_active", "transfer_source_no_longer_active"])


if __name__ == "__main__":
    unittest.main()
