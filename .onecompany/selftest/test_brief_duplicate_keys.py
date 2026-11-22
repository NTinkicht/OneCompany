"""Saved Product Brief reads refuse duplicate JSON keys (OC-P0-12/13)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.brief_status import summarize
from scripts.brief_validate import validate
from scripts.first_run_journey import read_brief

BRIEF = {
    "schema_version": "1.0",
    "document_kind": "product_brief_draft",
    "status": "DRAFT_NOT_APPROVED",
    "source": "owner_supplied_answers_and_read_only_discovery",
    "project": {"name": "Example", "repository": "owner/example", "default_branch": "main",
                "path": "adopt", "known_stack": [], "existing_tests": [],
                "existing_ci": [], "known_contracts": []},
    "answers": {"audience": "Operators", "problem": "Manual handoffs",
                "outcome": "Faster triage", "first_feature": "Status view", "constraints": None},
    "missing_required_answers": [],
    "acceptance_criteria": [],
    "approval": {"product_brief": False, "implementation": False, "deployment": False},
    "write_lease_granted": False,
    "qualified_implementer_selected": False,
    "safety_blockers": [],
    "next_action": "Review this draft; saving is NOT approval.",
}
TOP = '"write_lease_granted": false'
NESTED = '"deployment": false'


class BriefDuplicateKeyTests(unittest.TestCase):
    def path(self, text):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "brief.json"
        path.write_text(text, encoding="utf-8")
        return path

    def duplicated(self, marker):
        text = json.dumps(BRIEF)
        self.assertEqual(text.count(marker), 1)
        # Identical repeated value: only the duplication itself can justify refusal.
        return text.replace(marker, marker + ", " + marker)

    def test_control_without_duplicates_is_accepted(self):
        path = self.path(json.dumps(BRIEF))
        self.assertEqual(read_brief(path)["status"], "DRAFT_NOT_APPROVED")
        self.assertTrue(validate(path)["valid"])
        self.assertNotEqual(summarize(path)["stage"], "BLOCKED")

    def test_duplicate_keys_are_refused_at_every_depth(self):
        for marker in (TOP, NESTED):
            with self.subTest(marker=marker):
                path = self.path(self.duplicated(marker))
                with self.assertRaisesRegex(ValueError, "DUPLICATE_JSON_KEY"):
                    read_brief(path)
                self.assertEqual(validate(path), {"valid": False, "status": "REFUSED_MALFORMED"})
                blocked = summarize(path)
                self.assertEqual(blocked["stage"], "BLOCKED")
                self.assertEqual(blocked["blockers"], ["unsafe_or_malformed_brief"])
                self.assertFalse(blocked["approved"])


if __name__ == "__main__":
    unittest.main()
