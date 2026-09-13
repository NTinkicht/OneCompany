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


def snapshot(scope: str) -> dict:
    return {
        "write_scope": [scope],
        "resource_locks": [],
        "parallelism": "auto",
        "risk_class": "LOW",
        "dependencies": [],
        "dependency_closure": [],
    }


class RejectedLeaseFailoverTests(unittest.TestCase):
    def test_transfer_from_rejected_assignment_is_rejected_not_integrity_conflict(self):
        assignment = {
            "role": "implementation",
            "work_unit": "WU-A",
            "branch": "wu-a",
            "pr": 1,
            "start_head": "a" * 40,
            "planning_snapshot": snapshot("src/a/**"),
        }
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {**assignment, "lease_id": "L1"}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {**assignment, "lease_id": "L2"}),
            event(
                3,
                "ROLE_LEASE_TRANSFERRED",
                "claude",
                {
                    **assignment,
                    "old_lease_id": "L2",
                    "new_lease_id": "L3",
                    "lease_id": "L3",
                    "start_head": "b" * 40,
                },
            ),
        ]
        result = derive(events)

        self.assertEqual([item["id"] for item in result["active_leases"]], ["L1"])
        self.assertEqual(result["integrity_conflicts"], [])
        rejected_ids = [item["rejected_lease_id"] for item in result["rejected_claims"]]
        self.assertEqual(rejected_ids, ["L2", "L3"])
        follow_on = result["rejected_claims"][1]
        self.assertEqual(follow_on["violations"][0]["reason"], "transfer_source_no_longer_active")
        self.assertEqual(follow_on["old_lease_id"], "L2")


if __name__ == "__main__":
    unittest.main()
