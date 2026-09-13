from __future__ import annotations
import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("assurance_gate", ROOT / "scripts" / "assurance_gate.py")
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class AssuranceGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = json.loads((ROOT / "examples" / "assurance" / "WU900.json").read_text())

    def test_merge_ready_reference_passes(self):
        errors, _ = gate.validate(copy.deepcopy(self.packet))
        self.assertEqual(errors, [])

    def test_undercoverage_fails(self):
        packet = copy.deepcopy(self.packet)
        packet["evidence"]["coverage"]["branch"] = 12
        errors, _ = gate.validate(packet)
        self.assertTrue(any("coverage.branch" in item for item in errors))

    def test_missing_required_test_family_evidence_fails(self):
        packet = copy.deepcopy(self.packet)
        del packet["evidence"]["test_family_results"]["security"]
        errors, _ = gate.validate(packet)
        self.assertTrue(any("required test family security" in item for item in errors))

    def test_stale_independent_review_fails(self):
        packet = copy.deepcopy(self.packet)
        packet["evidence"]["independent_review"]["sha"] = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        errors, _ = gate.validate(packet)
        self.assertTrue(any("independent review must target exact" in item for item in errors))

    def test_author_cannot_independently_review(self):
        packet = copy.deepcopy(self.packet)
        packet["evidence"]["independent_review"]["actor"] = "implementer-example"
        errors, _ = gate.validate(packet)
        self.assertTrue(any("cannot be a material author" in item for item in errors))

    def test_missing_objective_trace_fails(self):
        packet = copy.deepcopy(self.packet)
        packet["traceability"] = [x for x in packet["traceability"] if x["relationship"] != "objective_to_requirement"]
        errors, _ = gate.validate(packet)
        self.assertTrue(any("objective_to_requirement" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
