from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from schema_validate import validate

CONTROL = ROOT / ".onecompany"
SCHEMA = json.loads(
    (CONTROL / "schemas" / "external-capability-register.schema.json").read_text(encoding="utf-8")
)
REGISTER = json.loads(
    (CONTROL / "external-capability-register.json").read_text(encoding="utf-8")
)


class ExternalCapabilityRegisterTests(unittest.TestCase):
    def check(self, document):
        errors = []
        validate(document, SCHEMA, "external-capability-register.json", errors)
        return errors

    def test_planning_guardrails_cannot_be_erased_or_budget_raised(self):
        for mutation in (
            lambda d: d.update(authority=""),
            lambda d: d.update(planning_rules={}),
            lambda d: d["planning_rules"].update(owner_budget_USD_additional_monthly=999999),
        ):
            changed = copy.deepcopy(REGISTER)
            mutation(changed)
            self.assertTrue(self.check(changed), changed["planning_rules"])

    def test_full_inventory_is_valid(self):
        self.assertEqual([], self.check(REGISTER))

    def test_duplicate_id_even_if_metadata_differs_is_rejected(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][1]["capability_id"] = changed["candidates"][0]["capability_id"]
        errors = self.check(changed)
        self.assertTrue(any("duplicate" in e and "capability_id" in e for e in errors), errors)
        self.assertTrue(any("missing required capability_id" in e for e in errors), errors)

    def test_duplicate_repository_even_if_id_differs_is_rejected(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][1]["repository_or_project"] = changed["candidates"][0]["repository_or_project"]
        errors = self.check(changed)
        self.assertTrue(any("duplicate" in e and "repository_or_project" in e for e in errors), errors)
        self.assertTrue(any("missing required repository_or_project" in e for e in errors), errors)

    def test_duplicate_assessment_task_is_rejected(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][1]["candidate_assessment_task"] = changed["candidates"][0]["candidate_assessment_task"]
        errors = self.check(changed)
        self.assertTrue(any("duplicate" in e and "candidate_assessment_task" in e for e in errors), errors)

    def test_swapping_urls_cannot_misattribute_candidate(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][0]["candidate_url"], changed["candidates"][1]["candidate_url"] = (
            changed["candidates"][1]["candidate_url"], changed["candidates"][0]["candidate_url"]
        )
        errors = self.check(changed)
        self.assertTrue(any("candidate_url" in e and "identity" in e for e in errors), errors)

    def test_swapping_ids_does_not_reassign_repository_or_work_unit(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][0]["capability_id"], changed["candidates"][1]["capability_id"] = (
            changed["candidates"][1]["capability_id"], changed["candidates"][0]["capability_id"]
        )
        errors = self.check(changed)
        self.assertTrue(any("repository_or_project" in e and "identity" in e for e in errors), errors)

    def test_unique_but_wrong_assessment_task_is_rejected(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][-1]["candidate_assessment_task"] = "ASSESS-EXT-999"
        errors = self.check(changed)
        self.assertTrue(any("candidate_assessment_task" in e and "identity" in e for e in errors), errors)

    def test_work_unit_mapping_cannot_be_misattributed(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][0]["work_unit_mappings"] = ["WU-P2-HAR-001"]
        errors = self.check(changed)
        self.assertTrue(any("work_unit_mappings" in e and "identity" in e for e in errors), errors)

    def test_all_eleven_group_workstreams_are_required(self):
        changed = copy.deepcopy(REGISTER)
        changed["group_workstreams"][-1] = copy.deepcopy(changed["group_workstreams"][0])
        errors = self.check(changed)
        self.assertTrue(any("duplicate" in e and ".key" in e for e in errors), errors)
        self.assertTrue(any("missing required key" in e for e in errors), errors)

    def test_missing_candidate_cannot_pass_with_correct_length(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][-1] = copy.deepcopy(changed["candidates"][0])
        errors = self.check(changed)
        self.assertTrue(any("missing required capability_id" in e for e in errors), errors)


    def test_phase1_reconciliation_preserves_completed_work_and_new_ids(self):
        ledger = REGISTER["phase1_reconciliation"]
        self.assertEqual("2026-10-18", ledger["as_of_date"])
        self.assertEqual(61, len(REGISTER["candidates"]))
        self.assertEqual(11, len(REGISTER["group_workstreams"]))
        closed = set(ledger["historically_completed_wus"])
        proposed = set(ledger["proposed_not_admitted_followups"])
        self.assertEqual(
            {
                "WU-P0-RECONCILE-001",
                "WU-P1-FOUNDATIONS-001",
                "WU-P1-DISCOVERY-001",
                "WU-P1-EXECUTION-002",
                "WU-P1-PREVIEW-001",
                "WU-P1-BRIEF-001",
                "WU-P1-RUNTIME-001",
                "WU-P1-QUALITY-001",
                "WU-P1-PLAYWRIGHT-001",
                "WU-P1-MISSION-EVIDENCE-001",
            },
            closed,
        )
        self.assertEqual(
            {
                "WU-P0-LIVE-RECONCILIATION-001",
                "WU-P1-BRIEF-APPROVAL-HANDOFF-001",
                "WU-P1-RUNTIME-BINDING-001",
                "WU-P1-POSTBIND-ASSURANCE-001",
                "WU-P1-MISSION-TRUTH-001",
            },
            proposed,
        )
        self.assertFalse(closed & proposed)
        self.assertEqual("WU-P1-E2E-001", ledger["existing_open_not_admitted_integration"])
        self.assertIn("never admits", ledger["source_of_truth"])

    def test_no_obsolete_phase1_aliases_or_closed_runtime_reused_in_plans(self):
        ledger = REGISTER["phase1_reconciliation"]
        self.assertEqual(
            {
                "WU-P1-VERTICAL-001": "WU-P1-E2E-001",
                "WU-P1-MISSION-001": "WU-P1-MISSION-TRUTH-001",
            },
            ledger["obsolete_phase1_proposal_aliases"],
        )
        group_mappings = [
            wu
            for group in REGISTER["group_workstreams"]
            for wu in [group["wu"], *group["deps"]]
        ]
        candidate_mappings = [
            wu
            for candidate in REGISTER["candidates"]
            for wu in [*candidate["dependencies"], *candidate["work_unit_mappings"]]
        ]
        all_planned_mappings = group_mappings + candidate_mappings
        for obsolete in (
            "WU-P1-VERTICAL-001",
            "WU-P1-MISSION-001",
            "WU-P1-RUNTIME-001",
            "WU-P1-QUALITY-001",
            "WU-P1-PLAYWRIGHT-001",
        ):
            self.assertNotIn(obsolete, all_planned_mappings)
        spec = next(g for g in REGISTER["group_workstreams"] if g["key"] == "SPEC")
        self.assertEqual("WU-P1-BRIEF-APPROVAL-HANDOFF-001", spec["wu"])
        self.assertIn("WU-P1-DISCOVERY-001", spec["deps"])
        self.assertIn("WU-P1-RUNTIME-BINDING-001", all_planned_mappings)
        self.assertIn("WU-P1-POSTBIND-ASSURANCE-001", all_planned_mappings)
        self.assertIn("WU-P1-E2E-001", all_planned_mappings)
        self.assertIn("WU-P1-MISSION-TRUTH-001", all_planned_mappings)

    def test_schema_rejects_restoring_completed_discovery_as_proposed_group(self):
        changed = copy.deepcopy(REGISTER)
        spec = next(g for g in changed["group_workstreams"] if g["key"] == "SPEC")
        spec["wu"] = "WU-P1-DISCOVERY-001"
        self.assertTrue(self.check(changed))

    def test_schema_rejects_old_candidate_mapping_or_missing_ledger(self):
        changed = copy.deepcopy(REGISTER)
        spec_candidate = next(
            c for c in changed["candidates"] if c["capability_id"] == "EXT-024"
        )
        spec_candidate["work_unit_mappings"] = ["WU-P1-DISCOVERY-001"]
        self.assertTrue(self.check(changed))
        changed = copy.deepcopy(REGISTER)
        del changed["phase1_reconciliation"]
        self.assertTrue(self.check(changed))


if __name__ == "__main__":
    unittest.main()
