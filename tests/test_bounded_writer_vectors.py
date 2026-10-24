"""OC-P0-07 bounded writer vectors: one writer per WU, bounded selection, stop when no eligible work."""
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
sys.path.insert(0, str(ROOT / "tests"))

import next_work  # noqa: E402
from planning_lib import active_work_items, select_parallel_set  # noqa: E402
from test_scheduler_vectors import planning, wu  # noqa: E402


def ids(items):
    return [item.get("id") for item in items]


class MalformedLeaseOccupiesSlotTests(unittest.TestCase):
    """A live implementation lease that cannot be matched to a WU must fail closed."""

    QUEUE = [wu("WU-A", ["a/**"]), wu("WU-B", ["b/**"])]
    MALFORMED = [
        {"role": "implementation"},
        {"work_unit": None, "role": "implementation"},
        {"work_unit": 7, "role": "implementation"},
        {"work_unit": "", "role": "implementation"},
        {"work_unit": ["WU-A"], "role": "implementation"},
    ]

    def test_malformed_lease_consumes_the_only_slot(self):
        for lease in self.MALFORMED:
            with self.subTest(lease=lease):
                plan = select_parallel_set(self.QUEUE, planning(1), [lease])
                self.assertEqual(plan["active_count"], 1)
                self.assertEqual(plan["available_slots"], 0)
                self.assertEqual(plan["selected"], [])

    def test_malformed_lease_conflicts_with_all_work_when_slots_remain(self):
        for lease in self.MALFORMED:
            with self.subTest(lease=lease):
                plan = select_parallel_set(self.QUEUE, planning(3), [lease])
                self.assertEqual(plan["active_count"], 1)
                self.assertEqual(plan["selected"], [])
                self.assertEqual(sorted(ids(plan["blocked"])), ["WU-A", "WU-B"])

    def test_malformed_lease_snapshot_cannot_narrow_the_placeholder(self):
        lease = {"role": "implementation", "planning_snapshot": {"write_scope": ["zzz/**"], "parallelism": "auto"}}
        (item,) = active_work_items([lease], {})
        self.assertEqual(item["parallelism"], "serial")
        self.assertEqual(item["resource_locks"], ["*"])
        self.assertEqual(item["risk_class"], "CRITICAL")

    def test_non_dict_lease_entry_fails_closed(self):
        plan = select_parallel_set(self.QUEUE, planning(1), ["WU-A"])  # type: ignore[list-item]
        self.assertEqual(plan["active_count"], 1)
        self.assertEqual(plan["selected"], [])

    def test_well_formed_lease_path_unchanged(self):
        plan = select_parallel_set(self.QUEUE, planning(2), [{"work_unit": "WU-A", "role": "implementation"}])
        self.assertEqual(plan["active_count"], 1)
        self.assertEqual(ids(plan["selected"]), ["WU-B"])
        self.assertIn({"id": "WU-A", "reasons": ["WU-A:same_work_unit"]}, plan["blocked"])


class OneWriterPerWorkUnitTests(unittest.TestCase):
    def test_leased_work_unit_is_never_selected_again(self):
        plan = select_parallel_set([wu("WU-A", ["a/**"])], planning(5), [{"work_unit": "WU-A", "role": "implementation"}])
        self.assertEqual(plan["selected"], [])
        self.assertEqual(plan["blocked"], [{"id": "WU-A", "reasons": ["WU-A:same_work_unit"]}])

    def test_selection_never_exceeds_available_slots(self):
        work = [wu(f"WU-{n}", [f"p{n}/**"]) for n in range(6)]
        for slots in range(1, 5):
            for active in range(0, slots + 1):
                leases = [{"work_unit": f"WU-L{n}", "role": "implementation"} for n in range(active)]
                with self.subTest(slots=slots, active=active):
                    plan = select_parallel_set(work, planning(slots), leases)
                    self.assertLessEqual(len(plan["selected"]), max(slots - active, 0))

    def test_proposed_work_is_not_started_without_planning_flag(self):
        work = [wu("WU-P", ["p/**"], status="PROPOSED")]
        self.assertEqual(select_parallel_set(work, planning())["selected"], [])
        self.assertEqual(ids(select_parallel_set(work, planning(), include_proposed=True)["selected"]), ["WU-P"])

    def test_durably_merged_work_unit_is_not_restarted(self):
        plan = select_parallel_set([wu("WU-M", ["m/**"])], planning(), [], {"WU-M"})
        self.assertEqual(plan["selected"], [])
        self.assertEqual(plan["ranked"], [])


class NextWorkStopVectors(unittest.TestCase):
    def run_next_work(self, work, *, leases=None, merged=None, slots=3, view_error=None, stop=False):
        loads: list[str] = []

        def fake_load(path):
            name = Path(path).name
            loads.append(name)
            if name == "queue.json":
                return {"work_units": work}
            if name == "planning.json":
                return planning(slots)
            raise AssertionError(f"unexpected load {path}")

        view = mock.Mock(return_value={"active_leases": leases or [], "verified_merged_work_units": merged or []})
        if view_error is not None:
            view.side_effect = view_error
        out = io.StringIO()
        with mock.patch.object(next_work, "emergency_stop_active", return_value=stop), mock.patch.object(
            next_work, "load_json", side_effect=fake_load
        ), mock.patch.object(next_work, "coordination_view", view), mock.patch.object(
            sys, "argv", ["next_work.py"]
        ), contextlib.redirect_stdout(out):
            code = next_work.main()
        return code, json.loads(out.getvalue()), loads, view

    def test_emergency_stop_selects_nothing_and_reads_no_state(self):
        code, payload, loads, view = self.run_next_work([wu("WU-A", ["a/**"])], stop=True)
        self.assertEqual(code, 0)
        self.assertEqual(payload, {"status": "EMERGENCY_STOP_ACTIVE", "candidates": []})
        self.assertEqual(loads, [])
        view.assert_not_called()

    def test_coordination_unavailable_blocks_with_nonzero_exit(self):
        code, payload, _, _ = self.run_next_work([wu("WU-A", ["a/**"])], view_error=RuntimeError("ledger down"))
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "BLOCKED_COORDINATION_UNAVAILABLE")
        self.assertEqual(payload["candidates"], [])

    def test_no_eligible_work_stops(self):
        for work in ([], [wu("WU-D", ["d/**"], status="DONE")], [wu("WU-P", ["p/**"], status="PROPOSED")]):
            with self.subTest(work=ids(work)):
                code, payload, _, _ = self.run_next_work(work)
                self.assertEqual(code, 0)
                self.assertEqual(payload["status"], "NO_READY_WORK")
                self.assertEqual(payload["candidates"], [])

    def test_durably_merged_only_queue_stops(self):
        code, payload, _, _ = self.run_next_work([wu("WU-M", ["m/**"])], merged=["WU-M"])
        self.assertEqual(payload["status"], "NO_READY_WORK")
        self.assertEqual(payload["durably_merged"], ["WU-M"])

    def test_wip_limit_reached(self):
        code, payload, _, _ = self.run_next_work(
            [wu("WU-B", ["b/**"])], leases=[{"work_unit": "WU-A", "role": "implementation"}], slots=1
        )
        self.assertEqual(payload["status"], "WIP_LIMIT_REACHED")
        self.assertEqual(payload["candidates"], [])

    def test_malformed_implementation_lease_reaches_wip_limit(self):
        code, payload, _, _ = self.run_next_work([wu("WU-B", ["b/**"])], leases=[{"role": "implementation"}], slots=1)
        self.assertEqual(payload["status"], "WIP_LIMIT_REACHED")
        self.assertEqual(payload["active_implementation_streams"], 1)
        self.assertEqual(payload["candidates"], [])

    def test_only_work_already_leased_is_not_restarted(self):
        code, payload, _, _ = self.run_next_work(
            [wu("WU-A", ["a/**"])], leases=[{"work_unit": "WU-A", "role": "implementation"}], slots=3
        )
        self.assertEqual(payload["status"], "NO_CONFLICT_FREE_READY_WORK")
        self.assertEqual(payload["candidates"], [])

    def test_review_lease_does_not_consume_writer_slot(self):
        code, payload, _, _ = self.run_next_work(
            [wu("WU-B", ["b/**"])], leases=[{"work_unit": "WU-A", "role": "review"}], slots=1
        )
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["active_implementation_streams"], 0)
        self.assertEqual(ids(payload["candidates"]), ["WU-B"])


if __name__ == "__main__":
    unittest.main()
