from __future__ import annotations
import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("assurance_gate", ROOT / "scripts" / "assurance_gate.py")
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
REFERENCE = ROOT / ".onecompany" / "reference" / "assurance" / "WU900.json"


class AssuranceGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = json.loads(REFERENCE.read_text(encoding="utf-8"))

    def test_merge_ready_reference_structure_passes(self):
        errors, _ = gate.validate_structure(copy.deepcopy(self.packet))
        self.assertEqual(errors, [])

    def test_undercoverage_claim_is_not_structural_authority(self):
        packet = copy.deepcopy(self.packet)
        packet["evidence"]["coverage"]["branch"] = 12
        errors, _ = gate.validate_structure(packet)
        self.assertEqual(errors, [])

    def test_missing_legacy_test_family_claim_is_not_structural_authority(self):
        packet = copy.deepcopy(self.packet)
        del packet["evidence"]["test_family_results"]["security"]
        errors, _ = gate.validate_structure(packet)
        self.assertEqual(errors, [])

    def test_stale_legacy_review_claim_is_not_structural_authority(self):
        packet = copy.deepcopy(self.packet)
        packet["evidence"]["independent_review"]["sha"] = "b" * 40
        errors, _ = gate.validate_structure(packet)
        self.assertEqual(errors, [])

    def test_legacy_self_review_claim_is_not_structural_authority(self):
        packet = copy.deepcopy(self.packet)
        packet["evidence"]["independent_review"]["actor"] = "implementer-example"
        errors, _ = gate.validate_structure(packet)
        self.assertEqual(errors, [])

    def test_missing_platform_review_reference_fails(self):
        packet = copy.deepcopy(self.packet)
        packet["evidence"].pop("review_reference", None)
        errors, _ = gate.validate_structure(packet)
        self.assertTrue(any("review_reference" in item for item in errors), errors)

    def test_missing_objective_trace_fails(self):
        packet = copy.deepcopy(self.packet)
        packet["traceability"] = [x for x in packet["traceability"] if x["relationship"] != "objective_to_requirement"]
        errors, _ = gate.validate_structure(packet)
        self.assertTrue(any("objective_to_requirement" in item for item in errors), errors)


if __name__ == "__main__":
    unittest.main()
