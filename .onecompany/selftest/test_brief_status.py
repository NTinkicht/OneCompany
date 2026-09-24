import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

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
        missing = [
            key
            for key in ("problem", "audience", "outcome", "first_feature")
            if not isinstance(answers.get(key), str) or not answers[key].strip()
        ]
        return {
            "schema_version": "1.0",
            "document_kind": "product_brief_draft",
            "status": "DRAFT_NOT_APPROVED",
            "source": "owner_supplied_answers_and_read_only_discovery",
            "project": {"name": "demo"},
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

    def test_inconsistent_saved_missing_answers_are_blocked(self):
        payload = self.canonical({
            "problem": "P", "audience": "A", "outcome": "O", "first_feature": "F",
        })
        payload["missing_required_answers"] = ["problem"]
        result = summarize(self.write(payload))
        self.assertEqual(result["stage"], "BLOCKED")
        self.assertIn("inconsistent_missing_required_answers", result["blockers"])

    def test_authority_bearing_draft_is_blocked(self):
        payload = self.canonical({
            "problem": "P", "audience": "A", "outcome": "O", "first_feature": "F",
        })
        payload["approval"]["implementation"] = True
        result = summarize(self.write(payload))
        self.assertEqual(result["stage"], "BLOCKED")
        self.assertEqual(result["next_action"], "recreate_saved_brief_from_read_only_discovery")

    def test_noncanonical_status_is_blocked(self):
        payload = self.canonical({
            "problem": "P", "audience": "A", "outcome": "O", "first_feature": "F",
        })
        payload["status"] = "APPROVED"
        result = summarize(self.write(payload))
        self.assertEqual(result["stage"], "BLOCKED")
        self.assertIn("authority_bearing_or_noncanonical_brief", result["blockers"])

    def test_saved_safety_blockers_are_preserved(self):
        payload = self.canonical({
            "problem": "P", "audience": "A", "outcome": "O", "first_feature": "F",
        })
        payload["safety_blockers"] = ["repository_identity_unverified"]
        result = summarize(self.write(payload))
        self.assertEqual(result["stage"], "BLOCKED")
        self.assertEqual(result["blockers"], ["repository_identity_unverified"])
        self.assertEqual(result["next_action"], "resolve_discovery_safety_blockers")

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

    def test_deeply_nested_json_is_blocked_without_traceback(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "brief.json"
        path.write_text("[" * 1200 + "]" * 1200, encoding="utf-8")
        result = summarize(path)
        self.assertEqual(result["stage"], "BLOCKED")

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
