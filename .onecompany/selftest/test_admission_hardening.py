from __future__ import annotations

import argparse
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lease_core
from planning_lib import by_id, dependency_ready

A = "a" * 40
B = "b" * 40
BASE = "c" * 40


def work_graph() -> list[dict]:
    return [
        {
            "id": "WU-A",
            "status": "READY",
            "dependencies": ["WU-B"],
            "write_scope": ["src/a/**"],
            "resource_locks": [],
            "parallelism": "auto",
            "risk_class": "LOW",
        },
        {
            "id": "WU-B",
            "status": "DONE",
            "dependencies": ["WU-C"],
            "write_scope": ["src/b/**"],
            "resource_locks": [],
            "parallelism": "auto",
            "risk_class": "LOW",
        },
        {
            "id": "WU-C",
            "status": "READY",
            "dependencies": [],
            "write_scope": ["src/c/**"],
            "resource_locks": [],
            "parallelism": "auto",
            "risk_class": "LOW",
        },
    ]


class AdmissionHardeningTests(unittest.TestCase):
    def test_local_dependency_readiness_requires_transitive_closure(self):
        work_map = by_id(work_graph())
        ready, missing, unsatisfied = dependency_ready(
            work_map["WU-A"], work_map, {"WU-B"}
        )
        self.assertFalse(ready)
        self.assertEqual(missing, [])
        self.assertEqual(unsatisfied, ["WU-C"])

        ready, missing, unsatisfied = dependency_ready(
            work_map["WU-A"], work_map, {"WU-B", "WU-C"}
        )
        self.assertTrue(ready)
        self.assertEqual(missing, [])
        self.assertEqual(unsatisfied, [])

    def test_durable_preflight_requires_transitive_closure(self):
        work_map = by_id(work_graph())
        ready, unsatisfied = lease_core._durable_dependency_check(
            work_map["WU-A"], work_map, {"WU-B"}
        )
        self.assertFalse(ready)
        self.assertEqual(unsatisfied, ["WU-C"])

        ready, unsatisfied = lease_core._durable_dependency_check(
            work_map["WU-A"], work_map, {"WU-B", "WU-C"}
        )
        self.assertTrue(ready)
        self.assertEqual(unsatisfied, [])

    def _load_for_acquire(self, path: Path):
        name = Path(path).name
        if name == "state.json":
            return {"active_leases": [], "active_streams": []}
        if name == "queue.json":
            return {"work_units": work_graph()}
        if name == "planning.json":
            return {
                "parallel_execution": {
                    "enabled": True,
                    "max_concurrent_implementation_streams": 2,
                    "require_write_scope_for_parallel": True,
                    "critical_risk_default": "serialize",
                }
            }
        raise AssertionError(path)

    def test_durable_acquire_honors_base_trusted_emergency_stop(self):
        work_map = by_id(work_graph())
        context = {
            "config": {"safety": {"emergency_stop": True}},
            "work_item": work_map["WU-A"],
            "work_map": work_map,
            "planning": {},
            "policy_blobs": {},
            "actor_limit": 1,
            "actor_eligible": True,
            "actor_ineligibility_reasons": [],
        }
        args = argparse.Namespace(
            wu="WU-A",
            actor="worker",
            branch="feature/a",
            pr=7,
            start_head=A,
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(lease_core, "emergency_stop_active", return_value=False))
            stack.enter_context(patch.object(lease_core, "load_json", side_effect=self._load_for_acquire))
            stack.enter_context(patch.object(lease_core, "ledger_enabled", return_value=True))
            stack.enter_context(patch.object(lease_core, "authoritative", return_value=([], [])))
            stack.enter_context(patch.object(lease_core, "list_events", return_value=[]))
            stack.enter_context(
                patch.object(
                    lease_core,
                    "derive",
                    return_value={"verified_merged_work_units": []},
                )
            )
            stack.enter_context(patch.object(lease_core, "trusted_pr_base", return_value=BASE))
            stack.enter_context(
                patch.object(
                    lease_core,
                    "trusted_admission_context",
                    return_value=(context, None),
                )
            )
            post = stack.enter_context(patch.object(lease_core, "post_event"))
            rc = lease_core.acquire(args)
        self.assertEqual(rc, 2)
        post.assert_not_called()

    def test_durable_transfer_honors_base_trusted_emergency_stop(self):
        old = {
            "id": "L1",
            "role": "implementation",
            "actor": "worker",
            "work_unit": "WU-A",
            "branch": "feature/a",
            "pr": 7,
            "start_head": A,
            "status": "active",
            "planning_snapshot": {
                "dependencies": ["WU-B"],
                "dependency_closure": ["WU-B", "WU-C"],
                "write_scope": ["src/a/**"],
                "resource_locks": [],
                "parallelism": "auto",
                "risk_class": "LOW",
            },
        }
        context = {
            "config": {"safety": {"emergency_stop": True}},
            "planning": {},
            "policy_blobs": {},
            "actor_limit": 1,
            "actor_eligible": True,
            "actor_ineligibility_reasons": [],
            "work_map": by_id(work_graph()),
        }
        args = argparse.Namespace(
            lease_id="L1",
            actor="replacement",
            current_head=B,
            reason="capability_failover",
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(lease_core, "emergency_stop_active", return_value=False))
            stack.enter_context(patch.object(lease_core, "load_json", side_effect=self._load_for_acquire))
            stack.enter_context(patch.object(lease_core, "ledger_enabled", return_value=True))
            stack.enter_context(patch.object(lease_core, "authoritative", return_value=([old], [])))
            stack.enter_context(patch.object(lease_core, "trusted_pr_base", return_value=BASE))
            stack.enter_context(
                patch.object(
                    lease_core,
                    "trusted_admission_context",
                    return_value=(context, None),
                )
            )
            post = stack.enter_context(patch.object(lease_core, "post_event"))
            rc = lease_core.transfer(args)
        self.assertEqual(rc, 2)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
