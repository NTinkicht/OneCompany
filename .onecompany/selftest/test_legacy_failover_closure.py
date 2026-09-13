from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lease


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
        old = {
            "id": "L1",
            "work_unit": "WU-A",
            "role": "implementation",
            "actor": "first-worker",
            "branch": "wu-a",
            "pr": 10,
            "start_head": "a" * 40,
            "status": "active",
            "planning_snapshot": {
                "write_scope": ["src/a/**"],
                "resource_locks": [],
                "parallelism": "auto",
                "risk_class": "LOW",
                "dependencies": ["WU-B"],
            },
        }
        state = {
            "active_leases": [dict(old)],
            "active_streams": [lease._stream_from_lease(old)],
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

        def fake_load(path: Path):
            name = Path(path).name
            if name == "state.json":
                return state
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
        with (
            patch.object(lease, "emergency_stop_active", return_value=False),
            patch.object(lease, "load_json", side_effect=fake_load),
            patch.object(lease, "authoritative", return_value=([old], [])),
            patch.object(lease, "actor_capacity_state", return_value=(1, [], 0, 1)),
            patch.object(lease, "ledger_enabled", return_value=False),
            patch.object(lease, "sync_cache"),
            patch.object(lease, "save_json"),
        ):
            result = lease.transfer(args)

        self.assertEqual(result, 0)
        replacement = state["active_leases"][-1]
        replacement_snapshot = replacement["planning_snapshot"]
        self.assertEqual(replacement_snapshot["dependencies"], ["WU-B"])
        self.assertNotIn("dependency_closure", replacement_snapshot)


if __name__ == "__main__":
    unittest.main()
