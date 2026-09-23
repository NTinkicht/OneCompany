import json
import tempfile
import unittest
from pathlib import Path

from scripts.brief_validate import validate


class BriefValidateTests(unittest.TestCase):
    def write(self, payload):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "brief.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_complete_owner_brief_is_ready_but_not_approved(self):
        result = validate(self.write({
            "problem": "Manual handoffs",
            "audience": "Operators",
            "outcome": "Faster triage",
            "first_feature": "Status view",
        }))
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "PROPOSAL_READY_NOT_APPROVED")
        self.assertFalse(result["approved"])

    def test_missing_answer_remains_incomplete(self):
        result = validate(self.write({"problem": "P", "audience": "A"}))
        self.assertFalse(result["valid"])
        self.assertIn("outcome", result["missing"])

    def test_authority_bearing_brief_is_refused(self):
        result = validate(self.write({
            "problem": "P", "audience": "A", "outcome": "O",
            "first_feature": "F", "approved": True,
        }))
        self.assertEqual(result["status"], "REFUSED_AUTHORITY_BEARING")


if __name__ == "__main__":
    unittest.main()
