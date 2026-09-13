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

    def assert_fails_with(self, packet, text):
        errors, _ = assurance.validate_packet(packet)
        self.assertTrue(any(text in item for item in errors), errors)

    def test_reference_packet_passes(self):
        errors, warnings = assurance.validate_packet(self.packet())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_draft_can_be_incomplete(self):
        packet = {
            "work_unit": "WU000",
            "status": "draft",
            "objective": "Define an observable post-change outcome.",
            "risk_level": "medium",
            "quality_profile": "production",
            "code_change": True,
            "material_authors": [],
            "requirements": [],
            "acceptance_criteria": [],
            "risks": [],
            "traceability": [],
            "test_plan": {"families": [], "tests": []},
            "documentation_impact": {"declared": False, "types": []},
            "architecture_impact": {"significant": False, "adr_ids": []},
            "release": {"rollback_strategy": "", "observability_plan": ""},
            "evidence": {},
        }
        errors, warnings = assurance.validate_packet(packet)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_review_lifecycle_state_is_supported(self):
        packet = self.packet()
        packet["status"] = "review"
        errors, warnings = assurance.validate_packet(packet)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_merge_ready_requires_material_authorship_snapshot(self):
        packet = self.packet()
        packet.pop("material_authors")
        self.assert_fails_with(packet, "complete non-empty material_authors snapshot")

    def test_empty_merge_ready_material_authorship_snapshot_fails(self):
        packet = self.packet()
        packet["material_authors"] = []
        self.assert_fails_with(packet, "complete non-empty material_authors snapshot")

    def test_low_risk_ready_mitigation_need_not_have_test_trace_yet(self):
        packet = self.packet()
        packet["status"] = "ready"
        packet["risk_level"] = "low"
        risk = packet["risks"][0]
        risk["likelihood"] = 1
        risk["impact"] = 4
        risk["inherent_score"] = 4
        risk["residual_likelihood"] = 1
        risk["residual_impact"] = 1
        risk["residual_score"] = 1
        packet["traceability"] = [
            link for link in packet["traceability"] if link["relationship"] != "mitigation_to_test"
        ]
        errors, _ = assurance.validate_packet(packet)
        self.assertFalse(any("lacks verification test trace" in error for error in errors), errors)

    def test_high_risk_merge_mitigation_without_test_trace_fails(self):
        packet = self.packet()
        packet["traceability"] = [
            link for link in packet["traceability"] if link["relationship"] != "mitigation_to_test"
        ]
        self.assert_fails_with(packet, "mitigation MIT-900 lacks verification test trace")

    def test_regression_defect_test_target_is_supported(self):
        packet = self.packet()
        packet["test_plan"]["tests"][0]["covers"].append("DEFECT-42")
        errors, _ = assurance.validate_packet(packet)
        self.assertFalse(any("DEFECT-42" in error for error in errors), errors)

    def test_quality_fitness_test_target_is_supported(self):
        packet = self.packet()
        packet["test_plan"]["tests"][0]["covers"].append("FITNESS-kernel-import-direction")
        errors, _ = assurance.validate_packet(packet)
        self.assertFalse(any("FITNESS-kernel-import-direction" in error for error in errors), errors)

    def test_unknown_non_catalog_test_target_still_fails_closed(self):
        packet = self.packet()
        packet["test_plan"]["tests"][0]["covers"].append("MYSTERY-42")
        self.assert_fails_with(packet, "covers unknown trace target MYSTERY-42")

    def test_ambiguous_requirement_fails(self):
        packet = self.packet(); packet["requirements"][0]["statement"] = "The system shall be user-friendly."
        self.assert_fails_with(packet, "ambiguous/discouraged")

    def test_multiple_obligations_fail(self):
        packet = self.packet(); packet["requirements"][0]["statement"] = "The system shall deny deletion and shall emit an alert."
        self.assert_fails_with(packet, "one obligation")

    def test_empty_requirements_fail(self):
        packet = self.packet(); packet["requirements"] = []
        self.assert_fails_with(packet, "requirements must contain at least one")

    def test_empty_acceptance_criteria_fail(self):
        packet = self.packet(); packet["acceptance_criteria"] = []
        self.assert_fails_with(packet, "acceptance_criteria must contain at least one")

    def test_missing_traceability_fails(self):
        packet = self.packet(); packet["traceability"] = []
        self.assert_fails_with(packet, "traceability missing")

    def test_nonexistent_requirement_test_target_fails(self):
        packet = self.packet()
        for link in packet["traceability"]:
            if link["relationship"] == "requirement_to_test": link["target"] = "TEST-999"
        self.assert_fails_with(packet, "targets missing test TEST-999")

    def test_wrong_work_unit_target_fails(self):
        packet = self.packet()
        for link in packet["traceability"]:
            if link["relationship"] == "requirement_to_work_unit": link["target"] = "WU999"
        self.assert_fails_with(packet, "must target WU900")

    def test_incorrect_risk_score_fails(self):
        packet = self.packet(); packet["risks"][0]["inherent_score"] = 1
        self.assert_fails_with(packet, "inherent_score")

    def test_missing_candidate_sha_fails(self):
        packet = self.packet(); packet.pop("candidate_sha")
        self.assert_fails_with(packet, "requires candidate_sha")

    def test_stale_evidence_sha_fails(self):
        packet = self.packet(); packet["evidence"]["sha"] = "b" * 40
        self.assert_fails_with(packet, "evidence sha does not equal candidate_sha")

    def test_coverage_threshold_fails(self):
        packet = self.packet(); packet["evidence"]["coverage"]["line"] = 84
        self.assert_fails_with(packet, "below production threshold 85")

    def test_missing_coverage_metric_fails(self):
        packet = self.packet(); packet["evidence"]["coverage"].pop("mutation")
        self.assert_fails_with(packet, "coverage metric mutation is required")

    def test_missing_test_family_result_fails(self):
        packet = self.packet(); packet["evidence"]["test_family_results"].pop("security")
        self.assert_fails_with(packet, "test family security must have pass evidence")

    def test_missing_evidence_artifact_fails(self):
        packet = self.packet(); packet["evidence"]["artifacts"] = []
        self.assert_fails_with(packet, "requires evidence.artifacts")

    def test_self_review_fails(self):
        packet = self.packet(); packet["evidence"]["independent_review"]["actor"] = "implementer-example"
        self.assert_fails_with(packet, "is a material author")

    def test_stale_independent_review_sha_fails(self):
        packet = self.packet(); packet["evidence"]["independent_review"]["sha"] = "b" * 40
        self.assert_fails_with(packet, "independent_review.sha must equal candidate_sha")


if __name__ == "__main__":
    unittest.main()
