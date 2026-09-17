from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planner  # noqa: E402


class LearningPlannerTests(unittest.TestCase):
    def test_work_unit_receives_bounded_advisory_learning_preflight(self):
        work_item = {
            "id": "WU-TEST-001",
            "title": "Harden protected branch exact-head evidence",
            "work_kind": "ENABLER",
            "risk_class": "HIGH",
            "planning_refs": ["CAP-AUTHORITY"],
            "write_scope": ["scripts/gate.py", ".github/workflows/validate.yml"],
        }
        value = planner.learning_preflight(work_item)
        self.assertEqual(value["authority"], "advisory_only")
        self.assertEqual(value["authority_effects"], [])
        self.assertFalse(value["hard_gate_created"])
        self.assertLessEqual(len(value["lesson_ids"]), 8)
        self.assertIn("K-GEN-EXACT-STATE-001", value["lesson_ids"])


if __name__ == "__main__":
    unittest.main()
