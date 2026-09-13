from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from planning_lib import by_id, critical_path, priority_score, scopes_overlap, select_parallel_set, work_units_conflict


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.planning = {
            "parallel_execution": {
                "enabled": True,
                "max_concurrent_implementation_streams": 3,
                "require_write_scope_for_parallel": True,
                "critical_risk_default": "serialize",
            },
            "prioritization": {
                "weights": {"business_value": 1, "time_criticality": 1, "risk_reduction": 1, "dependency_unlock": 1}
            },
        }

    def wu(self, id, scope, priority=1, dependencies=None, locks=None, risk="LOW", inputs=None, size=1):
        item = {
            "id": id, "title": id, "status": "READY", "priority": priority,
            "dependencies": dependencies or [], "risk_class": risk,
            "write_scope": scope, "resource_locks": locks or [], "parallelism": "auto",
            "estimate": {"job_size": size, "confidence": 1.0, "unit": "relative_points"},
        }
        if inputs:
            item["priority_inputs"] = inputs
        return item

    def test_disjoint_scope(self):
        a = self.wu("WU-A", ["src/a/**"])
        b = self.wu("WU-B", ["src/b/**"])
        self.assertFalse(work_units_conflict(a, b, self.planning, by_id([a, b]))[0])

    def test_overlap_scope(self):
        a = self.wu("WU-A", ["src/a/**"])
        b = self.wu("WU-B", ["src/a/file.py"])
        conflict, reasons = work_units_conflict(a, b, self.planning, by_id([a, b]))
        self.assertTrue(conflict)
        self.assertIn("write_scope_overlap", reasons)

    def test_missing_scope_fails_closed(self):
        a = self.wu("WU-A", ["src/a/**"])
        b = self.wu("WU-B", [])
        conflict, reasons = work_units_conflict(a, b, self.planning, by_id([a, b]))
        self.assertTrue(conflict)
        self.assertIn("unknown_write_scope", reasons)

    def test_resource_namespace_lock(self):
        a = self.wu("WU-A", ["src/a/**"], locks=["db:*"])
        b = self.wu("WU-B", ["src/b/**"], locks=["db:schema"])
        self.assertTrue(work_units_conflict(a, b, self.planning, by_id([a, b]))[0])

    def test_priority_is_confidence_weighted_cost_of_delay_over_size(self):
        item = self.wu("WU-A", ["a"], inputs={"business_value": 50, "time_criticality": 20, "risk_reduction": 10, "dependency_unlock": 20}, size=2)
        item["estimate"]["confidence"] = 0.8
        self.assertAlmostEqual(priority_score(item, self.planning), 40.0)

    def test_parallel_set_excludes_conflict(self):
        a = self.wu("WU-A", ["src/a/**"], priority=10)
        b = self.wu("WU-B", ["src/b/**"], priority=9)
        c = self.wu("WU-C", ["src/a/file.py"], priority=8)
        result = select_parallel_set([a, b, c], self.planning)
        self.assertEqual([item["id"] for item in result["selected"]], ["WU-A", "WU-B"])

    def test_active_stream_consumes_slot_and_blocks_overlap(self):
        a = self.wu("WU-A", ["src/a/**"], priority=10)
        b = self.wu("WU-B", ["src/b/**"], priority=9)
        c = self.wu("WU-C", ["src/a/file.py"], priority=8)
        active = [{"id": "L1", "role": "implementation", "status": "active", "work_unit": "WU-A"}]
        result = select_parallel_set([a, b, c], self.planning, active)
        self.assertEqual([item["id"] for item in result["selected"]], ["WU-B"])
        self.assertTrue(any(row["id"] == "WU-C" for row in result["blocked"]))

    def test_critical_path(self):
        a = self.wu("WU-A", ["a"], size=2)
        a["status"] = "DONE"
        b = self.wu("WU-B", ["b"], dependencies=["WU-A"], size=3)
        c = self.wu("WU-C", ["c"], dependencies=["WU-B"], size=5)
        result = critical_path([a, b, c])
        self.assertEqual(result["path"], ["WU-A", "WU-B", "WU-C"])
        self.assertEqual(result["job_size"], 10)


if __name__ == "__main__":
    unittest.main()
