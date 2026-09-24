import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scripts.brief_validate import validate


class BriefValidateTests(unittest.TestCase):
    def write(self, payload):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "brief.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def canonical(self, **answer_overrides):
        answers = {
            "audience": "Operators",
            "problem": "Manual handoffs",
            "outcome": "Faster triage",
            "first_feature": "Status view",
            "constraints": None,
        }
        answers.update(answer_overrides)
        missing = [
            key for key in ("audience", "problem", "outcome", "first_feature")
            if not answers.get(key)
        ]
        return {
            "schema_version": "1.0",
            "document_kind": "product_brief_draft",
            "status": "DRAFT_NOT_APPROVED",
            "source": "owner_supplied_answers_and_read_only_discovery",
            "project": {
                "name": "Example", "repository": "owner/example",
                "default_branch": "main", "path": "adopt",
                "known_stack": [], "existing_tests": [], "existing_ci": [],
                "known_contracts": [],
            },
            "answers": answers,
            "missing_required_answers": missing,
            "acceptance_criteria": [],
            "approval": {
                "product_brief": False,
                "implementation": False,
                "deployment": False,
            },
            "write_lease_granted": False,
            "qualified_implementer_selected": False,
            "safety_blockers": [],
            "next_action": "Review this draft; saving is NOT approval.",
        }

    def test_exported_owner_brief_is_ready_but_not_approved(self):
        result = validate(self.write(self.canonical()))
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "PROPOSAL_READY_NOT_APPROVED")
        self.assertFalse(result["approved"])

    def test_missing_answer_remains_incomplete(self):
        result = validate(self.write(self.canonical(outcome=None)))
        self.assertFalse(result["valid"])
        self.assertIn("outcome", result["missing"])

    def test_authority_bearing_brief_is_refused(self):
        payload = self.canonical()
        payload["approval"]["implementation"] = True
        result = validate(self.write(payload))
        self.assertEqual(result["status"], "REFUSED_AUTHORITY_BEARING")

    def test_real_export_with_safety_blocker_is_never_ready(self):
        payload = self.canonical()
        payload["safety_blockers"] = ["target_has_production_secrets"]
        result = validate(self.write(payload))
        self.assertFalse(result["valid"])
        self.assertNotEqual(result["status"], "PROPOSAL_READY_NOT_APPROVED")

    def test_top_level_authority_is_not_ready(self):
        for key, value in (("run_key", "fake"),
                           ("approved", True),
                           ("deployment_authorized", True)):
            with self.subTest(key=key):
                payload = self.canonical()
                payload[key] = value
                self.assertFalse(validate(self.write(payload))["valid"])

    def test_flat_answer_object_is_not_a_saved_product_brief(self):
        result = validate(self.write({
            "problem": "P", "audience": "A", "outcome": "O", "first_feature": "F",
        }))
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "REFUSED_WRONG_KIND")

    def test_symlink_is_refused_by_bounded_nofollow_reader(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        real = root / "real.json"
        real.write_text(json.dumps(self.canonical()), encoding="utf-8")
        link = root / "brief.json"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        result = validate(link)
        self.assertFalse(result["valid"])
        self.assertIn(result["status"], {"REFUSED_UNSAFE_PATH", "REFUSED_MALFORMED"})


if __name__ == "__main__":
    unittest.main()
