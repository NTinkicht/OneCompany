from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger_lib import derive


def event(i: int, kind: str, actor: str, payload: dict) -> dict:
    return {
        "version": 1, "event_id": f"e{i}", "type": kind, "actor": actor, "payload": payload,
        "github_created_at": f"2026-01-01T00:00:{i:02d}Z", "github_comment_id": i,
    }


def snapshot(scope: str, locks=None) -> dict:
    return {"write_scope": [scope], "resource_locks": locks or [], "parallelism": "auto", "risk_class": "LOW", "dependencies": []}


class LedgerParallelismTests(unittest.TestCase):
    def test_disjoint_work_units_can_hold_parallel_leases(self):
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU-A", "pr": 1, "planning_snapshot": snapshot("src/a/**")}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {"lease_id": "L2", "role": "implementation", "work_unit": "WU-B", "pr": 2, "planning_snapshot": snapshot("src/b/**")}),
        ]
        self.assertEqual({x["id"] for x in derive(events)["active_leases"]}, {"L1", "L2"})

    def test_same_work_unit_second_lease_is_rejected(self):
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU-A", "pr": 1, "planning_snapshot": snapshot("src/a/**")}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {"lease_id": "L2", "role": "implementation", "work_unit": "WU-A", "pr": 2, "planning_snapshot": snapshot("src/a/**")}),
        ]
        result = derive(events)
        self.assertEqual([x["id"] for x in result["active_leases"]], ["L1"])
        self.assertEqual(result["conflicts"][0]["reason"], "implementation_lease_already_active_for_wu")

    def test_overlapping_scope_is_rejected(self):
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU-A", "pr": 1, "planning_snapshot": snapshot("src/a/**")}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {"lease_id": "L2", "role": "implementation", "work_unit": "WU-B", "pr": 2, "planning_snapshot": snapshot("src/a/file.py")}),
        ]
        result = derive(events)
        self.assertEqual([x["id"] for x in result["active_leases"]], ["L1"])
        self.assertEqual(result["conflicts"][0]["reason"], "implementation_scope_conflict")

    def test_merge_release_does_not_release_other_stream(self):
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU-A", "pr": 1, "planning_snapshot": snapshot("src/a/**")}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {"lease_id": "L2", "role": "implementation", "work_unit": "WU-B", "pr": 2, "planning_snapshot": snapshot("src/b/**")}),
            event(3, "ROLE_LEASE_RELEASED", "codex", {"lease_id": "L1", "pr": 1, "reason": "merged"}),
            event(4, "MERGED", "human-owner", {"pr": 1, "work_unit": "WU-A", "merge_sha": "m"}),
        ]
        result = derive(events)
        self.assertEqual([x["id"] for x in result["active_leases"]], ["L2"])
        self.assertIn("WU-A", result["merged_work_units"])


if __name__ == "__main__":
    unittest.main()
