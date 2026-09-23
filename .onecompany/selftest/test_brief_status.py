import json
import tempfile
import unittest
from pathlib import Path

from scripts.brief_status import summarize


class BriefStatusTests(unittest.TestCase):
    def write(self, payload):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "brief.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_complete_draft_reports_owner_decision_next(self):
        result = summarize(self.write({
            "problem": "P", "audience": "A", "outcome": "O", "first_feature": "F",
        }))
        self.assertEqual(result["stage"], "DRAFT_COMPLETE_NOT_APPROVED")
        self.assertEqual(result["next_action"], "request_explicit_owner_decision")
        self.assertFalse(result["approved"])

    def test_incomplete_draft_lists_missing_answers(self):
        result = summarize(self.write({"problem": "P"}))
        self.assertEqual(result["stage"], "DRAFT_INCOMPLETE")
        self.assertIn("audience", result["missing"])

    def test_authority_bearing_draft_is_blocked(self):
        result = summarize(self.write({"approved": True}))
        self.assertEqual(result["stage"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
