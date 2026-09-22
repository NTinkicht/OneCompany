from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import brief_handoff_proposal as handoff

HEAD, BASE = "a" * 40, "b" * 40


def draft(path="adopt"):
    """Return a complete owner-filled draft fixture with no authority."""
    return {
        "document_kind": "product_brief_draft",
        "status": "DRAFT_NOT_APPROVED",
        "approval": {"product_brief": False, "implementation": False, "deployment": False},
        "write_lease_granted": False, "qualified_implementer_selected": False,
        "acceptance_criteria": [], "safety_blockers": [], "missing_required_answers": [],
        "answers": {"audience": "Families", "problem": "Keep track of tasks",
                    "outcome": "See completed work", "first_feature": "Checklist",
                    "constraints": "No private data"},
        "project": {"name": "Checklist", "repository": "demo/checklist",
                    "default_branch": "main", "path": path,
                    "known_stack": ["Python"], "existing_tests": ["pytest"],
                    "existing_ci": ["workflow.yml"], "known_contracts": ["API v1"]},
    }


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

    def test_planning_adapter_preserves_assets_and_zero_authority(self):
        """Existing-core input preserves contracts/tests/CI and cannot spend/run."""
        proposal = handoff.propose(draft(), HEAD, BASE)
        planning = handoff.consume_for_planning(proposal, HEAD, BASE)
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

    def test_planning_adapter_rejects_stale_refs_or_execution_authority(self):
        """Consumption rejects stale refs and any injected RunKey/lease/WU."""
        proposal = handoff.propose(draft(), HEAD, BASE)
        with self.assertRaisesRegex(ValueError, "STALE_OR_UNVERIFIED_REVISION"):
            handoff.consume_for_planning(proposal, "c" * 40, BASE)
        for field, value in (("run_key", {"generation": 1}), ("lease_id", "lease"), ("canonical_work_unit", "WU-1")):
            poisoned = copy.deepcopy(proposal)
            poisoned[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "EXECUTION_AUTHORITY_PRESENT"):
                handoff.consume_for_planning(poisoned, HEAD, BASE)


if __name__ == "__main__":
    unittest.main()
