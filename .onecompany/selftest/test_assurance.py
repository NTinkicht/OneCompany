from __future__ import annotations
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("assurance", ROOT / "scripts" / "assurance.py")
assert SPEC and SPEC.loader
assurance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assurance)
REFERENCE = ROOT / ".onecompany" / "reference" / "assurance" / "WU900.json"

class AssuranceTests(unittest.TestCase):
    def packet(self):
        return json.loads(REFERENCE.read_text())
    def test_reference_packet_passes(self):
        errors, _ = assurance.validate_packet(self.packet()); self.assertEqual(errors, [])
    def test_ambiguous_requirement_fails(self):
        packet = self.packet(); packet["requirements"][0]["statement"] = "The system shall be user-friendly."
        errors, _ = assurance.validate_packet(packet); self.assertTrue(any("ambiguous/discouraged" in item for item in errors))
    def test_missing_traceability_fails(self):
        packet = self.packet(); packet["traceability"] = []
        errors, _ = assurance.validate_packet(packet); self.assertTrue(any("traceability missing" in item for item in errors))
    def test_incorrect_risk_score_fails(self):
        packet = self.packet(); packet["risks"][0]["inherent_score"] = 1
        errors, _ = assurance.validate_packet(packet); self.assertTrue(any("inherent_score" in item for item in errors))

if __name__ == "__main__": unittest.main()
