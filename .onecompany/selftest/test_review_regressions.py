from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lease


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
        old = {
            "id": "L1",
            "work_unit": "WU-1",
            "role": "implementation",
            "actor": "first-worker",
            "branch": "wu-1",
            "pr": 10,
            "start_head": "a" * 40,
            "status": "active",
            "planning_snapshot": {
                "write_scope": ["src/**"],
                "resource_locks": [],
                "parallelism": "auto",
                "risk_class": "LOW",
                "dependencies": [],
                "dependency_closure": [],
            },
        }
        state = {
            "active_leases": [dict(old)],
            "active_streams": [{
                "work_unit": "WU-1",
                "lease_id": "L1",
                "actor": "first-worker",
                "branch": "wu-1",
                "pr": 10,
                "head": "a" * 40,
                "base_sha": None,
                "status": "ACTIVE_IMPLEMENTATION",
                "gate": None,
                "material_authors": ["first-worker", "earlier-worker"],
                "open_blockers": [],
                "human_decision_required": False,
            }],
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
        authors = set(state["active_streams"][0]["material_authors"])
        self.assertEqual(authors, {"first-worker", "earlier-worker", "replacement-worker"})

    def test_authorization_planning_baselines_are_protected(self):
        governance = json.loads((ROOT / ".onecompany" / "governance.json").read_text(encoding="utf-8"))
        protected = set(governance["control_plane"]["protected_paths"])
        expected = {
            ".onecompany/queue.json",
            ".onecompany/portfolio.json",
            ".onecompany/requirements-catalog.json",
            ".onecompany/acceptance-criteria.json",
            ".onecompany/risk-register.json",
        }
        self.assertTrue(expected <= protected, sorted(expected - protected))


if __name__ == "__main__":
    unittest.main()
