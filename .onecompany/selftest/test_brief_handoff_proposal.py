from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import brief_handoff_proposal as handoff
import planner
from product_brief import make_draft

HEAD, BASE = "a" * 40, "b" * 40


def draft(path="adopt"):
    """Return a real producer-shaped, complete, unapproved owner draft."""
    assessment = {"journey": {
        "path": path,
        "safety_blockers": [],
        "product_brief_draft": {
            "project_name": "Checklist",
            "repository": "demo/checklist",
            "branch": "main",
            "known_stack": ["Python"],
            "existing_tests": ["pytest"],
            "existing_ci": ["workflow.yml"],
            "known_contracts": ["API v1"],
        },
    }}
    answers = {"audience": "Families", "problem": "Keep track of tasks",
               "outcome": "See completed work", "first_feature": "Checklist",
               "constraints": "No private data"}
    return make_draft(assessment, answers)


class BriefHandoffTests(unittest.TestCase):
    """Prove proposal and planning consumption remain fail-closed/read-only."""

    def test_create_and_adopt_preserve_assets_never_authorize(self):
        """Create/adopt discovery survives without granting execution authority."""
        for path in ("create", "adopt"):
            with self.subTest(path=path):
                value = handoff.propose(draft(path), HEAD, BASE)
                self.assertEqual(value["project"]["path"], path)
                self.assertEqual(value["project"]["existing_tests"], ["pytest"])
                self.assertEqual(value["project"]["known_contracts"], ["API v1"])
                self.assertEqual(value["source_refs_unverified"]["head"], HEAD)
                self.assertIsNone(value["run_key"])
                self.assertIsNone(value["canonical_work_unit"])
                self.assertEqual(value["authorization"], "NOT_GRANTED")
                self.assertEqual(value["acceptance_criteria"], [])

    def test_stale_short_or_same_head_base_refuses(self):
        """Proposal creation rejects malformed or non-distinct revisions."""
        for head, base in [(HEAD[:7], BASE), (HEAD, HEAD), ("z" * 40, BASE), (HEAD, "")]:
            with self.subTest(head=head, base=base), self.assertRaisesRegex(ValueError, "EXACT_DISTINCT"):
                handoff.propose(draft(), head, base)

    def test_unapproved_brief_must_never_smuggle_authority(self):
        """Draft fields cannot smuggle approval, lease, criteria, or blockers."""
        for key, value in [
            ("status", "APPROVED"), ("write_lease_granted", True),
            ("qualified_implementer_selected", True),
            ("approval", {"product_brief": True, "implementation": False, "deployment": False}),
            ("acceptance_criteria", ["already approved"]), ("safety_blockers", ["unsafe"]),
            ("missing_required_answers", ["problem"]),
        ]:
            with self.subTest(key=key):
                candidate = copy.deepcopy(draft())
                candidate[key] = value
                with self.assertRaises(ValueError):
                    handoff.propose(candidate, HEAD, BASE)

    def test_extra_authority_fields_are_refused_not_silently_discarded(self):
        """A forged positive authority claim must fail the entire handoff."""
        for key, value in (
            ("run_key", "forged"), ("approved", True),
            ("deployment_authorized", True), ("lease_id", "forged"),
            ("canonical_work_unit", "WU-FORGED"),
            ("source", "approved_trustworthy"),
            ("schema_version", "9.0"),
        ):
            with self.subTest(key=key):
                candidate = copy.deepcopy(draft())
                candidate[key] = value
                with self.assertRaises(ValueError):
                    handoff.propose(candidate, HEAD, BASE)

    def test_malformed_or_stale_derived_answers_cannot_reach_planner(self):
        for name, mutate in (
            ("extra answer", lambda d: d["answers"].update(owner_approved=True)),
            ("missing flag drift", lambda d: d.update(missing_required_answers=["outcome"])),
            ("next step drift", lambda d: d.update(next_action="Deploy immediately")),
            ("unbounded answer", lambda d: d["answers"].update(problem="A" * 1001)),
            ("false-like approval", lambda d: d["approval"].update(implementation=0)),
            ("project injection", lambda d: d["project"].update(run_key="fake")),
        ):
            with self.subTest(name=name):
                candidate = draft()
                mutate(candidate)
                with self.assertRaises(ValueError):
                    handoff.propose(candidate, HEAD, BASE)

    def test_real_cli_uses_same_canonical_guard_without_target_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            brief_file = folder / "brief.json"
            original = draft("create")
            brief_file.write_text(json.dumps(original), encoding="utf-8")
            command = [
                sys.executable, str(ROOT / "onecompany.py"), "brief-handoff",
                "--brief", str(brief_file), "--head", HEAD, "--base", BASE,
            ]
            success = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True, timeout=16)
            self.assertEqual(success.returncode, 0, success.stderr)
            proposal = json.loads(success.stdout)
            self.assertEqual(proposal["authorization"], "NOT_GRANTED")
            self.assertIsNone(proposal["run_key"])
            self.assertEqual(proposal["project"]["path"], "create")
            self.assertFalse((folder / "checklist").exists())
            self.assertEqual(json.loads(brief_file.read_text()), original)
            for key, value in (("run_key", "fake"), ("approved", True)):
                with self.subTest(key=key):
                    poisoned = copy.deepcopy(original)
                    poisoned[key] = value
                    brief_file.write_text(json.dumps(poisoned), encoding="utf-8")
                    rejected = subprocess.run(
                        command, cwd=ROOT, text=True, capture_output=True, timeout=16)
                    self.assertEqual(rejected.returncode, 2)
                    self.assertNotIn("NOT_GRANTED", rejected.stdout)
            # The earlier approval assertion must not vanish via last-key-wins
            # parsing before the canonical draft validator sees the document.
            raw = json.dumps(original).replace(
                '"status": "DRAFT_NOT_APPROVED"',
                '"status": "APPROVED", "status": "DRAFT_NOT_APPROVED"', 1,
            )
            brief_file.write_text(raw, encoding="utf-8")
            rejected = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True, timeout=16)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("DUPLICATE_PRODUCT_BRIEF_JSON_KEY", rejected.stderr)
            self.assertEqual(rejected.stdout, "")

    @unittest.skipUnless(os.name == "posix", "anchored safe reader needs POSIX")
    def test_cli_rejects_symlinked_parent_and_leaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            actual = folder / "real"
            actual.mkdir()
            target = actual / "brief.json"
            target.write_text(json.dumps(draft()), encoding="utf-8")
            linked_file = folder / "file.json"
            linked_file.symlink_to(target)
            linked_parent = folder / "shortcut"
            linked_parent.symlink_to(actual, target_is_directory=True)
            for candidate in (linked_file, linked_parent / "brief.json"):
                with self.subTest(path=candidate):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "onecompany.py"),
                         "brief-handoff", "--brief", str(candidate),
                         "--head", HEAD, "--base", BASE],
                        cwd=ROOT, text=True, capture_output=True, timeout=16)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(json.loads(target.read_text()), draft())

    def test_unknown_intent_and_existing_assets_refuse_fabrication(self):
        """Missing owner intent or discovered project assets fail closed."""
        for mutation in ("answer", "path", "assets"):
            candidate = draft()
            if mutation == "answer":
                candidate["answers"]["first_feature"] = None
            elif mutation == "path":
                candidate["project"]["path"] = "unknown"
            else:
                del candidate["project"]["existing_tests"]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                handoff.propose(candidate, HEAD, BASE)

    def test_existing_planner_entry_preserves_assets_and_zero_authority(self):
        """The real planner entry consumes the handoff without granting execution."""
        proposal = handoff.propose(draft(), HEAD, BASE)
        planning = planner.consume_brief_handoff(proposal, HEAD, BASE)
        self.assertEqual(planning["project"]["existing_tests"], ["pytest"])
        self.assertEqual(planning["project"]["existing_ci"], ["workflow.yml"])
        self.assertEqual(planning["project"]["known_contracts"], ["API v1"])
        self.assertEqual(planning["authorization"], "NOT_GRANTED")
        self.assertEqual(planning["acceptance_criteria"], [])
        self.assertIsNone(planning["run_key"])
        self.assertIsNone(planning["lease_id"])
        self.assertIsNone(planning["canonical_work_unit"])
        self.assertFalse(planning["provider_invocation"])
        self.assertEqual(planning["requested_extra_spend"], 0)

    def test_existing_planner_rejects_smuggled_authority_and_malformed_content(self):
        """The second untrusted handoff boundary cannot launder extra claims."""
        baseline = handoff.propose(draft(), HEAD, BASE)
        for label, mutate in (
            ("approved", lambda p: p.update(approved=True)),
            ("approval", lambda p: p.update(approval={"implementation": True})),
            ("deploy", lambda p: p.update(deployment_authorized=True)),
            ("spend", lambda p: p.update(spend_authorized=True)),
            ("extra RunKey", lambda p: p.update(RunKey={"generation": 1})),
            ("unrecognized state", lambda p: p.update(unknown_authority="grant")),
            ("missing canonical field", lambda p: p.pop("next_action")),
            ("forged project approval", lambda p: p["project"].update(approved=True)),
            ("invalid project path", lambda p: p["project"].update(path="remote")),
            ("false project identity", lambda p: p["project"].update(repository=False)),
            ("non-string asset", lambda p: p["project"]["existing_ci"].append(True)),
            ("extra owner authority", lambda p: p["owner_intent"].update(approved=True)),
            ("missing owner intent", lambda p: p["owner_intent"].pop("outcome")),
            ("empty owner intent", lambda p: p["owner_intent"].update(problem=" ")),
            ("non-string constraints", lambda p: p.update(constraints=True)),
            ("non-string next action", lambda p: p.update(next_action={"deploy": True})),
        ):
            with self.subTest(label=label):
                poisoned = copy.deepcopy(baseline)
                mutate(poisoned)
                with self.assertRaises(ValueError):
                    planner.consume_brief_handoff(poisoned, HEAD, BASE)

    def test_existing_planner_entry_rejects_stale_refs_or_execution_authority(self):
        """The real planner boundary rejects stale refs and injected authority."""
        proposal = handoff.propose(draft(), HEAD, BASE)
        with self.assertRaisesRegex(ValueError, "STALE_OR_UNVERIFIED_REVISION"):
            planner.consume_brief_handoff(proposal, "c" * 40, BASE)
        for field, value in (("run_key", {"generation": 1}), ("lease_id", "lease"), ("canonical_work_unit", "WU-1")):
            poisoned = copy.deepcopy(proposal)
            poisoned[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "EXECUTION_AUTHORITY_PRESENT"):
                planner.consume_brief_handoff(poisoned, HEAD, BASE)


if __name__ == "__main__":
    unittest.main()
