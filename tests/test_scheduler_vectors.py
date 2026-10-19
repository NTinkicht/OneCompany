"""OC-P0-03 scheduler vectors: determinism, no-idle, parallel set, dependency unlock, cycles."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import next_work  # noqa: E402
from planning_lib import DependencyCycleError, critical_path, rank_work, select_parallel_set  # noqa: E402


def planning(slots: int = 3) -> dict:
    return {
        "parallel_execution": {
            "enabled": True,
            "max_concurrent_implementation_streams": slots,
            "require_write_scope_for_parallel": True,
            "critical_risk_default": "serialize",
        },
        "prioritization": {
            "weights": {"business_value": 1, "time_criticality": 1, "risk_reduction": 1, "dependency_unlock": 1}
        },
    }


def wu(id, scope, value=1, status="READY", dependencies=None, locks=None, size=1, priority=1):
    return {
        "id": id,
        "title": id,
        "status": status,
        "priority": priority,
        "dependencies": dependencies or [],
        "risk_class": "LOW",
        "write_scope": scope,
        "resource_locks": locks or [],
        "parallelism": "auto",
        "estimate": {"job_size": size, "confidence": 1.0, "unit": "relative_points"},
        "priority_inputs": {"business_value": value, "time_criticality": 0, "risk_reduction": 0, "dependency_unlock": 0},
    }


def ids(items):
    return [item.get("id") for item in items]


def lease(work_unit):
    return {"work_unit": work_unit, "role": "implementation"}


class DeterminismTests(unittest.TestCase):
    def queue(self):
        return [
            wu("WU-A", ["a/**"], value=5, size=2),
            wu("WU-B", ["b/**"], value=5, size=2),
            wu("WU-C", ["c/**"], value=3, dependencies=["WU-D"]),
            wu("WU-D", ["d/**"], value=1, status="DONE", size=4),
            wu("WU-E", ["e/**"], value=8, size=1),
            wu("WU-F", ["a/sub/**"], value=4, size=1),
        ]

    def test_permuted_input_gives_identical_ranking_selection_and_critical_path(self):
        base = self.queue()
        expected_rank = ids(rank_work(base, planning()))
        expected_plan = select_parallel_set(base, planning())
        expected_path = critical_path(base)
        permutations = [list(reversed(base)), base[3:] + base[:3], [base[i] for i in (4, 1, 5, 0, 3, 2)]]
        for work in permutations:
            with self.subTest(order=ids(work)):
                self.assertEqual(ids(rank_work(work, planning())), expected_rank)
                plan = select_parallel_set(work, planning())
                self.assertEqual(ids(plan["selected"]), ids(expected_plan["selected"]))
                self.assertEqual(plan["blocked"], expected_plan["blocked"])
                self.assertEqual(critical_path(work), expected_path)

    def test_expected_pinned_order(self):
        self.assertEqual(ids(rank_work(self.queue(), planning())), ["WU-E", "WU-F", "WU-C", "WU-A", "WU-B", "WU-D"])
        self.assertEqual(critical_path(self.queue()), {"job_size": 5.0, "path": ["WU-D", "WU-C"]})


class NoIdleTests(unittest.TestCase):
    def test_blocked_top_priority_does_not_idle_free_slot_on_scope(self):
        work = [
            wu("WU-ACTIVE", ["src/core/**"], status="IN_PROGRESS"),
            wu("WU-TOP", ["src/core/api.py"], value=9),
            wu("WU-LOW", ["docs/**"], value=1),
        ]
        plan = select_parallel_set(work, planning(slots=2), [lease("WU-ACTIVE")])
        self.assertEqual(plan["available_slots"], 1)
        self.assertEqual(ids(plan["selected"]), ["WU-LOW"])
        self.assertEqual(plan["blocked"], [{"id": "WU-TOP", "reasons": ["WU-ACTIVE:write_scope_overlap"]}])

    def test_blocked_top_priority_does_not_idle_free_slot_on_resource_lock(self):
        work = [
            wu("WU-ACTIVE", ["a/**"], status="IN_PROGRESS", locks=["db:migrations"]),
            wu("WU-TOP", ["b/**"], value=9, locks=["db:*"]),
            wu("WU-LOW", ["c/**"], value=1, locks=["cache:warm"]),
        ]
        plan = select_parallel_set(work, planning(slots=2), [lease("WU-ACTIVE")])
        self.assertEqual(ids(plan["selected"]), ["WU-LOW"])
        self.assertEqual(plan["blocked"], [{"id": "WU-TOP", "reasons": ["WU-ACTIVE:resource_lock_overlap"]}])


class ParallelSetTests(unittest.TestCase):
    def test_independent_set_fills_every_slot_and_reports_wip_limit(self):
        work = [wu(f"WU-{n}", [f"area{n}/**"], value=10 - n) for n in range(5)]
        plan = select_parallel_set(work, planning(slots=3))
        self.assertEqual(ids(plan["selected"]), ["WU-0", "WU-1", "WU-2"])
        self.assertEqual(plan["blocked"], [{"id": "WU-3", "reasons": ["wip_limit"]}, {"id": "WU-4", "reasons": ["wip_limit"]}])

    def test_overlapping_candidates_are_not_selected_together(self):
        work = [wu("WU-X", ["src/**"], value=5), wu("WU-Y", ["src/lib/y.py"], value=4), wu("WU-Z", ["web/**"], value=3)]
        plan = select_parallel_set(work, planning(slots=3))
        self.assertEqual(ids(plan["selected"]), ["WU-X", "WU-Z"])
        self.assertEqual(plan["blocked"], [{"id": "WU-Y", "reasons": ["WU-X:write_scope_overlap"]}])


class DependencyUnlockTests(unittest.TestCase):
    def chain(self, root_status="READY"):
        return [
            wu("WU-ROOT", ["root/**"], status=root_status),
            wu("WU-MID", ["mid/**"], status="DONE", dependencies=["WU-ROOT"]),
            wu("WU-LEAF", ["leaf/**"], value=9, dependencies=["WU-MID"]),
        ]

    def test_transitive_dependency_not_done_blocks(self):
        plan = select_parallel_set(self.chain(root_status="IN_PROGRESS"), planning())
        self.assertNotIn("WU-LEAF", ids(plan["selected"]))
        self.assertIn(
            {"id": "WU-LEAF", "reasons": ["dependency_not_ready"], "missing": [], "unsatisfied": ["WU-ROOT"]},
            plan["blocked"],
        )

    def test_done_closure_unlocks(self):
        plan = select_parallel_set(self.chain(root_status="DONE"), planning())
        self.assertEqual(ids(plan["selected"]), ["WU-LEAF"])

    def test_durably_merged_closure_unlocks(self):
        plan = select_parallel_set(self.chain(root_status="IN_PROGRESS"), planning(), durable_done={"WU-ROOT"})
        self.assertEqual(ids(plan["selected"]), ["WU-LEAF"])

    def test_unknown_dependency_blocks_as_missing(self):
        work = [wu("WU-ORPHAN", ["o/**"], dependencies=["WU-GHOST"])]
        plan = select_parallel_set(work, planning())
        self.assertEqual(plan["selected"], [])
        self.assertEqual(
            plan["blocked"], [{"id": "WU-ORPHAN", "reasons": ["dependency_not_ready"], "missing": ["WU-GHOST"], "unsatisfied": []}]
        )


class DependencyCycleTests(unittest.TestCase):
    def cyclic(self):
        return [
            wu("WU-A", ["a/**"], dependencies=["WU-B"]),
            wu("WU-B", ["b/**"], dependencies=["WU-A"]),
            wu("WU-C", ["c/**"], value=9),
        ]

    def test_critical_path_raises_dedicated_error(self):
        with self.assertRaises(DependencyCycleError):
            critical_path(self.cyclic())
        self.assertTrue(issubclass(DependencyCycleError, ValueError))

    def test_cycle_fails_closed_without_selecting_anything(self):
        plan = select_parallel_set(self.cyclic(), planning())
        self.assertEqual(plan["selected"], [])
        self.assertEqual(plan["ranked"], [])
        self.assertEqual(
            plan["blocked"],
            [{"id": "WU-A", "reasons": ["dependency_cycle"]}, {"id": "WU-B", "reasons": ["dependency_cycle"]}, {"id": "WU-C", "reasons": ["dependency_cycle"]}],
        )
        self.assertIn("dependency cycle involving", plan["dependency_cycle"])

    def test_cycle_among_non_candidates_still_fails_closed(self):
        work = [
            wu("WU-OLD1", ["x/**"], status="DONE", dependencies=["WU-OLD2"]),
            wu("WU-OLD2", ["y/**"], status="DONE", dependencies=["WU-OLD1"]),
            wu("WU-NEW", ["z/**"]),
        ]
        plan = select_parallel_set(work, planning())
        self.assertEqual(plan["selected"], [])
        self.assertEqual(plan["blocked"], [{"id": "WU-NEW", "reasons": ["dependency_cycle"]}])

    def test_acyclic_plan_has_no_cycle_marker(self):
        plan = select_parallel_set([wu("WU-C", ["c/**"])], planning())
        self.assertNotIn("dependency_cycle", plan)

    def run_next_work(self, work):
        def fake_load(path):
            name = Path(path).name
            if name == "queue.json":
                return {"work_units": work}
            if name == "planning.json":
                return planning()
            raise AssertionError(f"unexpected load {path}")

        out = io.StringIO()
        with mock.patch.object(next_work, "emergency_stop_active", return_value=False), mock.patch.object(
            next_work, "load_json", side_effect=fake_load
        ), mock.patch.object(
            next_work, "coordination_view", return_value={"active_leases": [], "verified_merged_work_units": []}
        ), mock.patch.object(sys, "argv", ["next_work.py"]), contextlib.redirect_stdout(out):
            code = next_work.main()
        return code, json.loads(out.getvalue())

    def test_next_work_reports_blocked_dependency_cycle(self):
        code, payload = self.run_next_work(self.cyclic())
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "BLOCKED_DEPENDENCY_CYCLE")
        self.assertEqual(payload["candidates"], [])
        self.assertIn("dependency cycle involving", payload["error"])

    def test_next_work_ready_path_unchanged(self):
        code, payload = self.run_next_work([wu("WU-C", ["c/**"])])
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "READY")
        self.assertEqual([item["id"] for item in payload["candidates"]], ["WU-C"])


if __name__ == "__main__":
    unittest.main()
