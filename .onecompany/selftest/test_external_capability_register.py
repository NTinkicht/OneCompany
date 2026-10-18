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


    def assert_invalid(self, mutation):
        changed = copy.deepcopy(REGISTER)
        mutation(changed)
        self.assertTrue(self.check(changed), "unapproved dependency change accepted")

    @staticmethod
    def dependency_graph(document):
        edges = {}
        def put(wu, deps):
            edges.setdefault(wu, set()).update(deps)
        ledger = document["phase1_reconciliation"]
        for wu, deps in ledger["proposed_dependency_dag"].items():
            put(wu, deps)
        for group in document["group_workstreams"]:
            put(group["wu"], group["deps"])
        for candidate in document["candidates"]:
            for wu in candidate["work_unit_mappings"]:
                put(wu, candidate["dependencies"])
        visited, active = set(), set()
        def walk(node):
            if node in active:
                raise AssertionError("cycle: " + node)
            if node in visited:
                return
            active.add(node)
            for dep in edges.get(node, ()):
                walk(dep)
            active.remove(node)
            visited.add(node)
        for node in edges:
            walk(node)
        return edges

    def test_completed_vs_proposed_identity_and_admission(self):
        ledger = REGISTER["phase1_reconciliation"]
        historical = set(ledger["historically_completed_wus"])
        proposed = set(ledger["proposed_not_admitted_followups"])
        self.assertEqual("2026-10-18", ledger["as_of_date"])
        self.assertEqual(61, len(REGISTER["candidates"]))
        self.assertEqual(11, len(REGISTER["group_workstreams"]))
        self.assertEqual(set((
            "WU-P0-RECONCILE-001 WU-P1-FOUNDATIONS-001 "
            "WU-P1-DISCOVERY-001 WU-P1-EXECUTION-002 WU-P1-PREVIEW-001 "
            "WU-P1-BRIEF-001 WU-P1-RUNTIME-001 WU-P1-QUALITY-001 "
            "WU-P1-PLAYWRIGHT-001 WU-P1-MISSION-EVIDENCE-001 "
            "WU-P1-JOURNEY-001"
        ).split()), historical)
        self.assertEqual(set((
            "WU-P0-LIVE-RECONCILIATION-001 WU-P1-BRIEF-APPROVAL-HANDOFF-001 "
            "WU-P1-RUNTIME-BINDING-001 WU-P1-POSTBIND-ASSURANCE-001 "
            "WU-P1-MISSION-TRUTH-001"
        ).split()), proposed)
        self.assertFalse(historical & proposed)
        self.assertEqual("WU-P1-E2E-001", ledger["existing_open_not_admitted_integration"])
        self.assertIn("never admits", ledger["source_of_truth"])
        self.assertEqual({
            "WU-P1-VERTICAL-001": "WU-P1-E2E-001",
            "WU-P1-MISSION-001": "WU-P1-MISSION-TRUTH-001",
        }, ledger["obsolete_phase1_proposal_aliases"])
        used = [
            wu for g in REGISTER["group_workstreams"]
            for wu in [g["wu"], *g["deps"]]
        ] + [
            wu for c in REGISTER["candidates"]
            for wu in [*c["dependencies"], *c["work_unit_mappings"]]
        ]
        for obsolete in (
            "WU-P1-VERTICAL-001", "WU-P1-MISSION-001",
            "WU-P1-RUNTIME-001", "WU-P1-QUALITY-001", "WU-P1-PLAYWRIGHT-001",
        ):
            self.assertNotIn(obsolete, used)
        self.assert_invalid(lambda x: x.pop("phase1_reconciliation"))
        self.assert_invalid(lambda x: next(
            g for g in x["group_workstreams"] if g["key"] == "SPEC"
        ).update(wu="WU-P1-DISCOVERY-001"))

    def test_phase1_dag_no_cycles_and_required_historical_gates(self):
        dag = REGISTER["phase1_reconciliation"]["proposed_dependency_dag"]
        self.assertEqual([
            "WU-P1-BRIEF-APPROVAL-HANDOFF-001", "WU-P1-RUNTIME-001",
            "WU-P1-PREVIEW-001", "WU-P1-FOUNDATIONS-001",
        ], dag["WU-P1-RUNTIME-BINDING-001"])
        handoff = dag["WU-P1-BRIEF-APPROVAL-HANDOFF-001"]
        self.assertEqual(set(handoff), {
            "WU-P0-LIVE-RECONCILIATION-001", "WU-P1-FOUNDATIONS-001",
            "WU-P1-DISCOVERY-001", "WU-P1-BRIEF-001",
            "WU-P1-EXECUTION-002", "WU-P1-JOURNEY-001",
        })
        self.assertIn("WU-P1-POSTBIND-ASSURANCE-001", dag["WU-P1-E2E-001"])
        self.assertIn("WU-P1-RUNTIME-BINDING-001", dag["WU-P1-POSTBIND-ASSURANCE-001"])
        self.assertNotIn("WU-P1-E2E-001", dag["WU-P1-POSTBIND-ASSURANCE-001"])
        self.dependency_graph(REGISTER)
        altered = copy.deepcopy(REGISTER)
        next(c for c in altered["candidates"] if c["capability_id"] == "EXT-035")[
            "dependencies"
        ] = ["WU-P1-E2E-001"]
        with self.assertRaisesRegex(AssertionError, "cycle"):
            self.dependency_graph(altered)
        self.assertTrue(self.check(altered))

    def test_spec_ui_and_ops_candidates_share_full_gates(self):
        groups = {g["key"]: g for g in REGISTER["group_workstreams"]}
        candidates = {c["capability_id"]: c for c in REGISTER["candidates"]}
        spec = groups["SPEC"]
        dag = REGISTER["phase1_reconciliation"]["proposed_dependency_dag"]
        self.assertEqual("WU-P1-BRIEF-APPROVAL-HANDOFF-001", spec["wu"])
        self.assertEqual(spec["deps"], dag[spec["wu"]])
        for cid in ("EXT-024", "EXT-025", "EXT-026"):
            self.assertEqual([spec["wu"]], candidates[cid]["work_unit_mappings"])
            self.assertEqual(spec["deps"], candidates[cid]["dependencies"])
        for cid in ("EXT-048", "EXT-049", "EXT-050"):
            self.assertEqual(["WU-P2-UI-001"], candidates[cid]["work_unit_mappings"])
            self.assertEqual(groups["UI"]["deps"], candidates[cid]["dependencies"])
        self.assertIn("WU-P1-E2E-001", groups["UI"]["deps"])
        self.assertTrue(set(groups["OPS"]["deps"]).issubset(
            candidates["EXT-018"]["dependencies"]
        ))
        self.assertEqual(
            ["WU-P1-RUNTIME-BINDING-001"], candidates["EXT-035"]["dependencies"]
        )
        self.assertEqual(
            {"WU-P1-POSTBIND-ASSURANCE-001", "WU-P2-UI-001"},
            set(candidates["EXT-035"]["work_unit_mappings"]),
        )
        for cid, dep in (
            ("EXT-024", "WU-P1-JOURNEY-001"),
            ("EXT-048", "WU-P1-E2E-001"),
            ("EXT-018", "WU-P2-OBS-001"),
        ):
            self.assert_invalid(lambda x, cid=cid, dep=dep: next(
                c for c in x["candidates"] if c["capability_id"] == cid
            )["dependencies"].remove(dep))
        self.assert_invalid(lambda x: x["phase1_reconciliation"][
            "proposed_dependency_dag"
        ][spec["wu"]].remove("WU-P1-JOURNEY-001"))

    def test_schema_pins_all_61_candidates_11_groups_and_six_dag_nodes(self):
        props = SCHEMA["properties"]
        gv = props["group_workstreams"]["x-expectedRowsByKey"]["values"]
        cv = props["candidates"]["x-expectedRowsByKey"]["values"]
        dv = props["phase1_reconciliation"]["properties"][
            "proposed_dependency_dag"
        ]["properties"]
        dag = REGISTER["phase1_reconciliation"]["proposed_dependency_dag"]
        self.assertEqual(11, len(gv))
        self.assertEqual(61, len(cv))
        self.assertEqual(set(dag), set(dv))
        for g in REGISTER["group_workstreams"]:
            self.assertEqual(g["deps"], gv[g["key"]]["deps"])
        for c in REGISTER["candidates"]:
            self.assertEqual(c["dependencies"], cv[c["capability_id"]]["dependencies"])
        for wu, deps in dag.items():
            self.assertEqual(deps, dv[wu]["const"])
            self.assert_invalid(lambda x, wu=wu: x["phase1_reconciliation"][
                "proposed_dependency_dag"
            ][wu].pop())
        for key in ("MEM", "SPEC", "UI"):
            self.assert_invalid(lambda x, key=key: next(
                g for g in x["group_workstreams"] if g["key"] == key
            ).update(deps=[]))
        for cid in ("EXT-024", "EXT-035", "EXT-048", "EXT-018"):
            self.assert_invalid(lambda x, cid=cid: next(
                c for c in x["candidates"] if c["capability_id"] == cid
            ).update(dependencies=[]))


if __name__ == "__main__":
    unittest.main()
