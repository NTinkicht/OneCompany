import json
import tempfile
import unittest
from pathlib import Path

from scripts.brief_status import summarize


class BriefStatusTests(unittest.TestCase):
    def write(self, payload):
        """Write one temporary JSON Product Brief and return its path."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "brief.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def canonical(self, answers):
        """Build the authority-free shape used by saved Product Brief drafts."""
        return {
            "status": "DRAFT_NOT_APPROVED",
            "answers": answers,
            "approval": {
                "product_brief": False,
                "implementation": False,
                "deployment": False,
            },
            "write_lease_granted": False,
            "qualified_implementer_selected": False,
        }

    def test_complete_draft_reports_owner_decision_next(self):
        result = summarize(self.write(self.canonical({
            "problem": "P", "audience": "A", "outcome": "O", "first_feature": "F",
        })))
        self.assertEqual(result["stage"], "DRAFT_COMPLETE_NOT_APPROVED")
        self.assertEqual(result["next_action"], "request_explicit_owner_decision")
        self.assertFalse(result["approved"])

    def test_incomplete_draft_lists_missing_answers(self):
        result = summarize(self.write(self.canonical({"problem": "P"})))
        self.assertEqual(result["stage"], "DRAFT_INCOMPLETE")
        self.assertIn("audience", result["missing"])

    def test_authority_bearing_draft_is_blocked(self):
        payload = self.canonical({
            "problem": "P", "audience": "A", "outcome": "O", "first_feature": "F",
        })
        payload["approval"]["implementation"] = True
        result = summarize(self.write(payload))
        self.assertEqual(result["stage"], "BLOCKED")
        self.assertEqual(result["next_action"], "remove_unverified_authority_and_revalidate")
        self.assertEqual(result["missing"], list(("problem", "audience", "outcome", "first_feature")))

    def test_top_level_answer_shape_is_not_misreported_as_saved_brief(self):
        result = summarize(self.write({
            "problem": "P", "audience": "A", "outcome": "O", "first_feature": "F",
        }))
        self.assertEqual(result["stage"], "BLOCKED")
        self.assertIn("missing_answers_object", result["blockers"])

    def test_malformed_json_is_blocked_with_next_step(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "brief.json"
        path.write_text("{not-json", encoding="utf-8")
        result = summarize(path)
        self.assertEqual(result["stage"], "BLOCKED")
        self.assertEqual(result["next_action"], "recreate_saved_brief")

    def test_non_object_json_is_blocked(self):
        result = summarize(self.write([]))
        self.assertEqual(result["stage"], "BLOCKED")
        self.assertIn("unsafe_or_malformed_brief", result["blockers"])

    def test_symlinked_brief_is_blocked(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / "target.json"
        path = Path(directory.name) / "brief.json"
        target.write_text(json.dumps(self.canonical({})), encoding="utf-8")
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("test environment cannot create symlinks")
        result = summarize(path)
        self.assertEqual(result["stage"], "BLOCKED")
        self.assertIn("unsafe_or_malformed_brief", result["blockers"])

    def test_oversized_brief_is_blocked(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "brief.json"
        path.write_bytes(b"x" * (16_384 + 1))
        result = summarize(path)
        self.assertEqual(result["stage"], "BLOCKED")
        self.assertIn("unsafe_or_malformed_brief", result["blockers"])


if __name__ == "__main__":
    unittest.main()
