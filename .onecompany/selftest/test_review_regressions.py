from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lease
from onecompany_lib import path_matches_any


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


class ReviewRegressionTests(unittest.TestCase):
    def test_local_stream_starts_with_lease_actor_as_material_author(self):
        stream = lease._stream_from_lease({
            "id": "L1",
            "work_unit": "WU-1",
            "actor": "implementer",
            "branch": "wu-1",
            "pr": 10,
            "start_head": "a" * 40,
        })
        self.assertEqual(stream["material_authors"], ["implementer"])

    def test_direct_acquire_rejects_unsatisfied_dependency(self):
        state = {"active_leases": [], "active_streams": []}
        queue = {
            "work_units": [
                {
                    "id": "WU-A",
                    "status": "PROPOSED",
                    "dependencies": [],
                    "write_scope": ["src/a/**"],
                    "resource_locks": [],
                    "parallelism": "auto",
                    "risk_class": "LOW",
                },
                {
                    "id": "WU-B",
                    "status": "READY",
                    "dependencies": ["WU-A"],
                    "write_scope": ["src/b/**"],
                    "resource_locks": [],
                    "parallelism": "auto",
                    "risk_class": "LOW",
                },
            ]
        }
        planning = {"parallel_execution": {"max_concurrent_implementation_streams": 3, "enabled": True}}

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
            wu="WU-B",
            actor="worker",
            branch="wu-b",
            start_head="b" * 40,
            pr=None,
        )
        with (
            patch.object(lease, "emergency_stop_active", return_value=False),
            patch.object(lease, "load_json", side_effect=fake_load),
            patch.object(lease, "ledger_enabled", return_value=False),
            patch.object(lease, "authoritative", return_value=([], [])),
            patch.object(lease, "actor_capacity_state") as capacity,
            patch.object(lease, "save_json") as save,
        ):
            result = lease.acquire(args)

        self.assertEqual(result, 2)
        capacity.assert_not_called()
        save.assert_not_called()

    def test_failover_preserves_all_material_authors_in_local_mode(self):
        planning_snapshot = {
            "write_scope": ["src/**"],
            "resource_locks": [],
            "parallelism": "auto",
            "risk_class": "LOW",
            "dependencies": [],
            "dependency_closure": [],
        }
        queue = {"work_units": []}
        planning = {
            "parallel_execution": {
                "enabled": True,
                "max_concurrent_implementation_streams": 3,
                "require_write_scope_for_parallel": True,
                "critical_risk_default": "serialize",
            }
        }
        state_cache = {"active_leases": [], "active_streams": []}

        def fake_load(path: Path):
            name = Path(path).name
            if name == "state.json":
                return state_cache
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
                        "work_unit": "WU-1",
                        "branch": "wu-1",
                        "pr": 10,
                        "start_head": "a" * 40,
                        "planning_snapshot": planning_snapshot,
                    },
                )
                lease.lifecycle.append_coordination_event(
                    "MATERIAL_AUTHOR",
                    "earlier-worker",
                    {"pr": 10, "work_unit": "WU-1"},
                )
                result = lease.transfer(args)
                view = lease.lifecycle.coordination_view(10)

        self.assertEqual(result, 0)
        self.assertEqual(
            set(view["material_authors"]),
            {"first-worker", "earlier-worker", "replacement-worker"},
        )
        self.assertEqual(len(view["active_leases"]), 1)
        self.assertEqual(view["active_leases"][0]["actor"], "replacement-worker")

    def test_authorization_planning_baselines_are_protected(self):
        governance = json.loads((ROOT / ".onecompany" / "governance.json").read_text(encoding="utf-8"))
        patterns = governance["control_plane"]["protected_paths"]
        expected = {
            ".onecompany/queue.json",
            ".onecompany/portfolio.json",
            ".onecompany/requirements-catalog.json",
            ".onecompany/acceptance-criteria.json",
            ".onecompany/risk-register.json",
        }
        unprotected = sorted(
            path for path in expected if not path_matches_any(path, patterns)
        )
        self.assertEqual(unprotected, [])


if __name__ == "__main__":
    unittest.main()
