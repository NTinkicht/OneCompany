from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import assurance_gate

REFERENCE = ROOT / ".onecompany" / "reference" / "assurance" / "WU900.json"


class AssuranceGateTrustTests(unittest.TestCase):
    def packet(self) -> dict:
        return json.loads(REFERENCE.read_text(encoding="utf-8"))

    def test_legacy_quality_and_review_claims_are_not_structural_authority(self):
        packet = self.packet()
        packet["evidence"]["coverage"] = {
            "line": 0,
            "branch": 0,
            "changed_line": 0,
            "mutation": 0,
        }
        packet["evidence"]["test_family_results"] = {
            family: "fail" for family in packet["test_plan"]["families"]
        }
        packet["evidence"]["gates"] = {"independent_review": "fail"}
        packet["evidence"]["independent_review"] = {
            "actor": "implementer-example",
            "sha": "b" * 40,
            "verdict": "fail",
        }
        errors, warnings = assurance_gate.validate_structure(packet)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_merge_grade_structure_requires_platform_references(self):
        packet = self.packet()
        packet["evidence"].pop("references", None)
        packet["evidence"].pop("review_reference", None)
        errors, _ = assurance_gate.validate_structure(packet)
        self.assertTrue(any("evidence.references" in error for error in errors), errors)
        self.assertTrue(any("review_reference" in error for error in errors), errors)

    def test_reference_ids_back_structural_test_to_evidence_links(self):
        packet = self.packet()
        packet["evidence"]["artifacts"] = []
        errors, _ = assurance_gate.validate_structure(packet)
        self.assertEqual(errors, [])

    def test_malformed_platform_reference_fails_before_live_verification(self):
        packet = self.packet()
        packet["evidence"]["references"][0]["workflow_run_id"] = 0
        errors, _ = assurance_gate.validate_structure(packet)
        self.assertTrue(any("positive workflow_run_id" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
