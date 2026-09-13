from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lease


def base_view(*_args, **_kwargs) -> dict:
    return {
        "active_leases": [],
        "material_authors": [],
        "current_gate": None,
        "gates_by_pr": {},
        "rejected_claims": [],
        "integrity_conflicts": [],
        "conflicts": [],
        "resolved_conflict_ids": [],
        "merged_work_units": [],
        "verified_merged_work_units": [],
        "current_actor_eligibility": {},
    }


class LegacyFailoverClosureTests(unittest.TestCase):
    def test_planning_snapshot_does_not_invent_transitive_closure(self):
        snapshot = lease.planning_snapshot(
            {
                "id": "WU-A",
                "write_scope": ["src/a/**"],
                "resource_locks": [],
                "parallelism": "auto",
                "risk_class": "LOW",
                "dependencies": ["WU-B"],
            }
        )
        self.assertEqual(snapshot["dependencies"], ["WU-B"])
        self.assertNotIn("dependency_closure", snapshot)

    def test_failover_preserves_unknown_legacy_dependency_closure(self):
        planning_snapshot = {
            "write_scope": ["src/a/**"],
            "resource_locks": [],
            "parallelism": "auto",
            "risk_class": "LOW",
            "dependencies": ["WU-B"],
        }
        queue = {
            "work_units": [
                {"id": "WU-A", "dependencies": ["WU-B"]},
                {"id": "WU-B", "dependencies": ["WU-C"]},
                {"id": "WU-C", "dependencies": []},
            ]
        }
        planning = {
            "parallel_execution": {
                "enabled": True,
                "max_concurrent_implementation_streams": 3,
                "require_write_scope_for_parallel": True,
                "critical_risk_default": "serialize",
            }
        }
        cache = {"active_leases": [], "active_streams": []}

        def fake_load(path: Path):
            name = Path(path).name
            if name == "state.json":
                return cache
            if name == "queue.json":
                return queue
            if name == "planning.json":
                return planning
            raise AssertionError(f"unexpected load: {path}")

        args = argparse.Namespace(
            lease_id="L1",
            actor="replacement-worker",
            current_head="b" * 40,
            reason="failover",
        )
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "lease-events.jsonl"
            with (
                patch.object(lease, "emergency_stop_active", return_value=False),
                patch.object(lease, "load_json", side_effect=fake_load),
                patch.object(lease, "actor_capacity_state", return_value=(1, [], 0, 1)),
                patch.object(lease, "ledger_enabled", return_value=False),
                patch.object(lease.lifecycle.ledger_lib, "ledger_enabled", return_value=False),
                patch.object(lease.lifecycle.ledger_lib, "derive", side_effect=base_view),
                patch.object(lease.lifecycle, "_local_event_path", return_value=event_path),
                patch.object(lease, "save_json"),
            ):
                lease.lifecycle.append_coordination_event(
                    "ROLE_LEASE_ASSIGNED",
                    "first-worker",
                    {
                        "lease_id": "L1",
                        "role": "implementation",
                        "work_unit": "WU-A",
                        "branch": "wu-a",
                        "pr": 10,
                        "start_head": "a" * 40,
                        "planning_snapshot": planning_snapshot,
                    },
                )
                result = lease.transfer(args)
                view = lease.lifecycle.coordination_view(10)

        self.assertEqual(result, 0)
        replacement = next(item for item in view["active_leases"] if item["id"] != "L1")
        replacement_snapshot = replacement["planning_snapshot"]
        self.assertEqual(replacement_snapshot["dependencies"], ["WU-B"])
        self.assertNotIn("dependency_closure", replacement_snapshot)
        self.assertEqual(replacement["parent_lease_id"], "L1")


if __name__ == "__main__":
    unittest.main()
