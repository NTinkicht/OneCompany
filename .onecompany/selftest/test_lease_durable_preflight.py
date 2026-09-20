from __future__ import annotations

import argparse
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lease

TRUSTED_REF = "b" * 40


class DurableLeasePreflightTests(unittest.TestCase):
    def test_native_durable_dependency_hook_accepts_three_arguments(self):
        # Live Pilot C lease acquire exposed an old two-arg wrapper hooked into
        # the core's three-arg seam. Confirm both zero-dependency and complete
        # transitive dependency paths before any durable event may be emitted.
        work_map = {
            "WU-A": {"id": "WU-A", "dependencies": ["WU-B"]},
            "WU-B": {"id": "WU-B", "dependencies": ["WU-C"]},
            "WU-C": {"id": "WU-C", "dependencies": []},
        }
        candidate = dict(work_map["WU-A"])
        candidate["dependency_closure"] = ["WU-B", "WU-C"]
        check = lease._durable_dependency_check
        self.assertEqual(check(work_map["WU-C"], work_map, set()), (True, []))
        self.assertEqual(check(candidate, work_map, set()), (False, ["WU-B", "WU-C"]))
        self.assertEqual(check(candidate, work_map, {"WU-B"}), (False, ["WU-C"]))
        self.assertEqual(check(candidate, work_map, {"WU-B", "WU-C"}), (True, []))
        # Even an incomplete frozen snapshot cannot bypass the protected map.
        candidate["dependency_closure"] = []
        self.assertEqual(check(candidate, work_map, {"WU-B"}), (False, ["WU-C"]))

    def test_queue_done_dependency_without_durable_merge_is_rejected_before_append(self):
        state = {"active_leases": [], "active_streams": []}
        queue = {
            "work_units": [
                {
                    "id": "WU-A",
                    "status": "READY",
                    "branch": "wu-a",
                    "pr": 14,
                    "dependencies": ["WU-B"],
                    "write_scope": ["src/a/**"],
                    "resource_locks": [],
                    "parallelism": "auto",
                    "risk_class": "LOW",
                },
                {
                    "id": "WU-B",
                    "status": "DONE",
                    "dependencies": [],
                    "write_scope": ["src/b/**"],
                    "resource_locks": [],
                    "parallelism": "auto",
                    "risk_class": "LOW",
                },
            ]
        }
        planning = {
            "parallel_execution": {
                "enabled": True,
                "max_concurrent_implementation_streams": 2,
                "require_write_scope_for_parallel": True,
                "critical_risk_default": "serialize",
            }
        }
        trusted_candidate = dict(queue["work_units"][0])
        trusted_context = {
            "work_item": trusted_candidate,
            "work_map": {item["id"]: item for item in queue["work_units"]},
            "planning": planning,
            "policy_blobs": {
                "queue": "1" * 40,
                "planning": "2" * 40,
                "actors": "3" * 40,
                "readiness": "4" * 40,
                "budget": "5" * 40,
            },
            "actor_limit": 1,
            "actor_eligible": True,
            "actor_ineligibility_reasons": [],
        }

        def fake_load(path: Path):
            name = Path(path).name
            if name == "state.json":
                return state
            if name == "queue.json":
                return queue
            if name == "planning.json":
                return planning
            raise AssertionError(path)

        args = argparse.Namespace(
            wu="WU-A",
            actor="codex",
            branch="wu-a",
            start_head="a" * 40,
            pr=14,
        )
        with (
            patch.object(lease, "emergency_stop_active", return_value=False),
            patch.object(lease, "load_json", side_effect=fake_load),
            patch.object(lease, "ledger_enabled", return_value=True),
            patch.object(lease, "authoritative", return_value=([], [])),
            patch.object(lease, "list_events", return_value=[]),
            patch.object(lease, "derive", return_value={"merged_work_units": []}),
            patch.object(lease, "trusted_pr_base", return_value=TRUSTED_REF),
            patch.object(
                lease,
                "trusted_admission_context",
                return_value=(trusted_context, None),
            ),
            patch.object(lease, "post_event") as post_event,
            patch.object(lease, "save_json") as save_json,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                result = lease.acquire(args)

        self.assertIn("lacks durable MERGED dependency evidence", output.getvalue())
        self.assertEqual(result, 2)
        post_event.assert_not_called()
        save_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
