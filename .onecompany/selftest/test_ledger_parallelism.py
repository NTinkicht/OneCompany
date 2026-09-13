from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger_lib import derive


def event(i: int, kind: str, actor: str, payload: dict, event_id: str | None = None) -> dict:
    return {
        "version": 1,
        "event_id": event_id or f"e{i}",
        "type": kind,
        "actor": actor,
        "payload": payload,
        "github_created_at": f"2026-01-01T00:00:{i:02d}Z",
        "github_comment_id": i,
    }


def snapshot(scope: str, locks=None, dependencies=None, dependency_closure=None) -> dict:
    dependencies = dependencies or []
    return {
        "write_scope": [scope],
        "resource_locks": locks or [],
        "parallelism": "auto",
        "risk_class": "LOW",
        "dependencies": dependencies,
        "dependency_closure": dependency_closure if dependency_closure is not None else list(dependencies),
    }


def legacy_snapshot(scope: str, dependencies=None) -> dict:
    """Pre-0.4 snapshot: direct dependencies only, no provable transitive closure."""
    return {
        "write_scope": [scope],
        "resource_locks": [],
        "parallelism": "auto",
        "risk_class": "LOW",
        "dependencies": dependencies or [],
    }


class LedgerParallelismTests(unittest.TestCase):
    def test_disjoint_work_units_can_hold_parallel_leases(self):
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU-A", "pr": 1, "planning_snapshot": snapshot("src/a/**")}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {"lease_id": "L2", "role": "implementation", "work_unit": "WU-B", "pr": 2, "planning_snapshot": snapshot("src/b/**")}),
        ]
        result = derive(events)
        self.assertEqual({x["id"] for x in result["active_leases"]}, {"L1", "L2"})
        self.assertEqual(result["integrity_conflicts"], [])

    def test_same_work_unit_second_lease_is_informational_rejection(self):
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU-A", "pr": 1, "planning_snapshot": snapshot("src/a/**")}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {"lease_id": "L2", "role": "implementation", "work_unit": "WU-A", "pr": 2, "planning_snapshot": snapshot("src/a/**")}),
        ]
        result = derive(events)
        self.assertEqual([x["id"] for x in result["active_leases"]], ["L1"])
        self.assertEqual(result["integrity_conflicts"], [])
        self.assertEqual(result["conflicts"], [])
        rejected = result["rejected_claims"][0]
        self.assertEqual(rejected["rejected_lease_id"], "L2")
        self.assertIn("implementation_lease_already_active_for_wu", {item["reason"] for item in rejected["violations"]})

    def test_overlapping_scope_is_informational_rejection(self):
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU-A", "pr": 1, "planning_snapshot": snapshot("src/a/**")}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {"lease_id": "L2", "role": "implementation", "work_unit": "WU-B", "pr": 2, "planning_snapshot": snapshot("src/a/file.py")}),
        ]
        result = derive(events)
        self.assertEqual([x["id"] for x in result["active_leases"]], ["L1"])
        self.assertEqual(result["integrity_conflicts"], [])
        rejected = result["rejected_claims"][0]
        details = {detail for item in rejected["violations"] for detail in item.get("details", [])}
        self.assertIn("write_scope_overlap", details)

    def test_historical_rejection_does_not_deadlock_future_lease(self):
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU-A", "pr": 1, "planning_snapshot": snapshot("src/a/**")}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {"lease_id": "L2", "role": "implementation", "work_unit": "WU-A", "pr": 2, "planning_snapshot": snapshot("src/a/**")}),
            event(3, "ROLE_LEASE_RELEASED", "codex", {"lease_id": "L1", "pr": 1, "reason": "merged"}),
            event(4, "MERGED", "human-owner", {"pr": 1, "work_unit": "WU-A", "merge_sha": "m"}),
            event(5, "ROLE_LEASE_ASSIGNED", "claude", {"lease_id": "L3", "role": "implementation", "work_unit": "WU-C", "pr": 3, "planning_snapshot": snapshot("src/c/**")}),
        ]
        result = derive(events)
        self.assertEqual([x["id"] for x in result["active_leases"]], ["L3"])
        self.assertEqual(result["integrity_conflicts"], [])
        self.assertTrue(result["rejected_claims"])

    def test_transitive_dependency_closure_is_enforced_from_snapshot(self):
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "LC", "role": "implementation", "work_unit": "WU-C", "pr": 1, "planning_snapshot": snapshot("src/c/**")}),
            event(2, "ROLE_LEASE_ASSIGNED", "claude", {"lease_id": "LA", "role": "implementation", "work_unit": "WU-A", "pr": 2, "planning_snapshot": snapshot("src/a/**", dependencies=["WU-B"], dependency_closure=["WU-B", "WU-C"])}),
        ]
        result = derive(events)
        self.assertEqual([x["id"] for x in result["active_leases"]], ["LC"])
        rejected = result["rejected_claims"][0]
        details = {detail for item in rejected["violations"] for detail in item.get("details", [])}
        self.assertIn("dependency_relationship", details)

    def test_legacy_snapshot_without_transitive_closure_serializes(self):
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "LC", "role": "implementation", "work_unit": "WU-C", "pr": 1, "planning_snapshot": snapshot("src/c/**")}),
            event(2, "ROLE_LEASE_ASSIGNED", "claude", {"lease_id": "LA", "role": "implementation", "work_unit": "WU-A", "pr": 2, "planning_snapshot": legacy_snapshot("src/a/**", dependencies=["WU-B"])}),
        ]
        result = derive(events)
        self.assertEqual([x["id"] for x in result["active_leases"]], ["LC"])
        rejected = next(item for item in result["rejected_claims"] if item["rejected_lease_id"] == "LA")
        details = {detail for item in rejected["violations"] for detail in item.get("details", [])}
        self.assertIn("unknown_dependency_closure", details)
        self.assertEqual(result["integrity_conflicts"], [])

    def test_losing_concurrent_transfer_is_informational_rejection(self):
        transfer_payload = {
            "role": "implementation",
            "work_unit": "WU-A",
            "branch": "wu-a",
            "pr": 1,
            "start_head": "b" * 40,
            "planning_snapshot": snapshot("src/a/**"),
        }
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU-A", "branch": "wu-a", "pr": 1, "start_head": "a" * 40, "planning_snapshot": snapshot("src/a/**")}),
            event(2, "ROLE_LEASE_TRANSFERRED", "claude", {**transfer_payload, "old_lease_id": "L1", "new_lease_id": "L2", "lease_id": "L2"}),
            event(3, "ROLE_LEASE_TRANSFERRED", "chatgpt", {**transfer_payload, "old_lease_id": "L1", "new_lease_id": "L3", "lease_id": "L3"}),
        ]
        result = derive(events)
        self.assertEqual([x["id"] for x in result["active_leases"]], ["L2"])
        self.assertEqual(result["integrity_conflicts"], [])
        rejected = next(item for item in result["rejected_claims"] if item["rejected_lease_id"] == "L3")
        self.assertEqual(rejected["violations"][0]["reason"], "transfer_source_no_longer_active")

    def test_unknown_transfer_source_remains_integrity_conflict(self):
        events = [
            event(1, "ROLE_LEASE_TRANSFERRED", "claude", {"old_lease_id": "NEVER", "new_lease_id": "L2", "lease_id": "L2", "role": "implementation", "work_unit": "WU-A", "pr": 1, "planning_snapshot": snapshot("src/a/**")}),
        ]
        result = derive(events)
        self.assertEqual(result["active_leases"], [])
        self.assertEqual(len(result["integrity_conflicts"]), 1)
        self.assertEqual(result["integrity_conflicts"][0]["reason"], "transfer_source_unknown")

    def test_integrity_conflict_requires_explicit_resolution_event(self):
        events = [
            event(1, "SUPERVISION_CHECK", "chatgpt", {"state": "first"}, event_id="dup"),
            event(2, "SUPERVISION_CHECK", "chatgpt", {"state": "replay"}, event_id="dup"),
        ]
        result = derive(events)
        self.assertEqual(len(result["integrity_conflicts"]), 1)
        conflict_id = result["integrity_conflicts"][0]["conflict_id"]
        events.append(event(3, "INTEGRITY_CONFLICT_RESOLVED", "human-owner", {"conflict_id": conflict_id, "reason": "investigated"}))
        resolved = derive(events)
        self.assertEqual(resolved["integrity_conflicts"], [])
        self.assertIn(conflict_id, resolved["resolved_conflict_ids"])

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
