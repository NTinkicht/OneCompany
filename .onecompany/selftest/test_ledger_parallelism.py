from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger_lib
from ledger_lib import derive as derive_live


def derive(events, pr=None):
    """Exercise ledger race algebra without depending on live actor readiness fixtures."""
    return derive_live(events, pr, enforce_actor_policy=False)


def event(
    i: int,
    kind: str,
    actor: str,
    payload: dict,
    event_id: str | None = None,
    *,
    version: int = 1,
) -> dict:
    return {
        "version": version,
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


def admission(
    actor: str,
    *,
    dependencies=None,
    dependencies_complete: bool = True,
    actor_eligible: bool = True,
    actor_limit: int = 2,
    source: str | None = None,
) -> dict:
    return {
        "schema": "onecompany-lease-admission-v1",
        "actor": actor,
        "actor_eligible": actor_eligible,
        "actor_ineligibility_reasons": [] if actor_eligible else ["disabled"],
        "actor_limit": actor_limit,
        "dependencies": sorted(dependencies or []),
        "dependencies_complete": dependencies_complete,
        "transfer_source_lease_id": source,
        "dependencies_inherited_from_source": source is not None,
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

    def test_v2_unfinished_dependency_is_rejected_at_admission(self):
        planning = snapshot("src/a/**", dependencies=["WU-B"], dependency_closure=["WU-B"])
        blocked_claim = event(
            2,
            "ROLE_LEASE_ASSIGNED",
            "codex",
            {
                "lease_id": "LA",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 2,
                "planning_snapshot": planning,
                "admission_snapshot": admission(
                    "codex", dependencies=["WU-B"], dependencies_complete=False
                ),
            },
            version=2,
        )
        blocked = derive([blocked_claim])
        self.assertEqual(blocked["active_leases"], [])
        rejection = blocked["rejected_claims"][0]
        self.assertIn(
            "dependency_not_complete_at_admission",
            {item["reason"] for item in rejection["violations"]},
        )

        accepted_claim = event(
            3,
            "ROLE_LEASE_ASSIGNED",
            "codex",
            {
                "lease_id": "LA2",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 2,
                "planning_snapshot": planning,
                "admission_snapshot": admission(
                    "codex", dependencies=["WU-B"], dependencies_complete=True
                ),
            },
            version=2,
        )
        unlocked = derive([
            event(1, "MERGED", "human-owner", {"pr": 1, "work_unit": "WU-B", "merge_sha": "m"}),
            accepted_claim,
        ])
        self.assertEqual([item["id"] for item in unlocked["active_leases"]], ["LA2"])

    def test_v2_ineligible_actor_claim_is_rejected_at_admission(self):
        claim = event(
            1,
            "ROLE_LEASE_ASSIGNED",
            "rogue",
            {
                "lease_id": "LR",
                "role": "implementation",
                "work_unit": "WU-R",
                "pr": 9,
                "planning_snapshot": snapshot("src/r/**"),
                "admission_snapshot": admission("rogue", actor_eligible=False),
            },
            version=2,
        )
        result = derive([claim])
        self.assertEqual(result["active_leases"], [])
        rejection = result["rejected_claims"][0]
        self.assertIn(
            "actor_implementation_ineligible_at_admission",
            {item["reason"] for item in rejection["violations"]},
        )

    def test_runtime_actor_ineligibility_preserves_accepted_lease_and_authorship(self):
        real_load = ledger_lib.load_json

        def fake_load(path):
            name = Path(path).name
            if name == "actors.json":
                return {
                    "actors": [
                        {"id": "worker", "enabled": False, "configured": True, "capabilities": ["implementation"], "cost_class": "FREE"},
                        {"id": "replacement", "enabled": True, "configured": True, "capabilities": ["implementation"], "cost_class": "FREE"},
                    ]
                }
            if name == "readiness.json":
                return {
                    "actors": [
                        {"actor_id": "worker", "setup_state": "ready", "verified_capabilities": ["implementation"], "temporarily_unavailable_capabilities": [], "repository_access": {"read": True, "write": True}, "capacity": {"implementation_streams": 1}},
                        {"actor_id": "replacement", "setup_state": "ready", "verified_capabilities": ["implementation"], "temporarily_unavailable_capabilities": [], "repository_access": {"read": True, "write": True}, "capacity": {"implementation_streams": 1}},
                    ]
                }
            return real_load(path)

        assignment = event(
            1,
            "ROLE_LEASE_ASSIGNED",
            "worker",
            {
                "lease_id": "L1",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 10,
                "planning_snapshot": snapshot("src/a/**"),
                "admission_snapshot": admission("worker", actor_limit=1),
            },
            version=2,
        )
        transfer = event(
            2,
            "ROLE_LEASE_TRANSFERRED",
            "replacement",
            {
                "lease_id": "L2",
                "new_lease_id": "L2",
                "old_lease_id": "L1",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 10,
                "planning_snapshot": snapshot("src/a/**"),
                "admission_snapshot": admission("replacement", actor_limit=1, source="L1"),
            },
            version=2,
        )
        with patch.object(ledger_lib, "load_json", side_effect=fake_load):
            before = derive_live([assignment], enforce_actor_policy=True)
            after = derive_live([assignment, transfer], 10, enforce_actor_policy=True)

        self.assertEqual([item["id"] for item in before["active_leases"]], ["L1"])
        self.assertEqual(before["material_authors"], ["worker"])
        self.assertFalse(before["current_actor_eligibility"]["L1"]["eligible"])
        self.assertIn("disabled", before["current_actor_eligibility"]["L1"]["reasons"])
        self.assertEqual([item["id"] for item in after["active_leases"]], ["L2"])
        self.assertEqual(set(after["material_authors"]), {"worker", "replacement"})

    def test_legacy_pre_v2_dependency_completion_is_grandfathered(self):
        claim = event(
            1,
            "ROLE_LEASE_ASSIGNED",
            "codex",
            {
                "lease_id": "LEGACY",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 1,
                "planning_snapshot": snapshot(
                    "src/a/**", dependencies=["WU-B"], dependency_closure=["WU-B"]
                ),
            },
            version=1,
        )
        result = derive([claim])
        self.assertEqual([item["id"] for item in result["active_leases"]], ["LEGACY"])
        self.assertEqual(result["rejected_claims"], [])

    def test_malformed_v2_admission_is_integrity_conflict(self):
        claim = event(
            1,
            "ROLE_LEASE_ASSIGNED",
            "codex",
            {
                "lease_id": "BROKEN",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 1,
                "planning_snapshot": snapshot("src/a/**"),
            },
            version=2,
        )
        result = derive([claim])
        self.assertEqual(result["active_leases"], [])
        self.assertEqual(result["integrity_conflicts"][0]["reason"], "invalid_lease_admission_evidence")

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
