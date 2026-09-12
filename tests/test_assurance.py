from __future__ import annotations
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("assurance", ROOT / "scripts" / "assurance.py")
assert SPEC and SPEC.loader
assurance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assurance)


class AssuranceTests(unittest.TestCase):
    def test_reference_packet_passes(self):
        packet = json.loads((ROOT / "examples" / "assurance" / "WU900.json").read_text())
        errors, _ = assurance.validate_packet(packet)
        self.assertEqual(errors, [])

    def test_ambiguous_requirement_fails(self):
        packet = json.loads((ROOT / "examples" / "assurance" / "WU900.json").read_text())
        packet["requirements"][0]["statement"] = "The system shall be user-friendly."
        errors, _ = assurance.validate_packet(packet)
        self.assertTrue(any("ambiguous/discouraged" in item for item in errors))

    def test_missing_traceability_fails(self):
        packet = json.loads((ROOT / "examples" / "assurance" / "WU900.json").read_text())
        packet["traceability"] = []
        errors, _ = assurance.validate_packet(packet)
        self.assertTrue(any("traceability missing" in item for item in errors))

    def test_incorrect_risk_score_fails(self):
        packet = json.loads((ROOT / "examples" / "assurance" / "WU900.json").read_text())
        packet["risks"][0]["inherent_score"] = 1
        errors, _ = assurance.validate_packet(packet)
        self.assertTrue(any("inherent_score" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
