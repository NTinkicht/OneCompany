import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("resume_product_brief", ROOT / "scripts" / "resume_product_brief.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def draft():
    return {
        "schema_version": "1.0",
        "document_kind": "product_brief_draft",
        "status": "DRAFT_NOT_APPROVED",
        "project": {"name": "Example"},
        "answers": {"audience": "Patients", "problem": "Waiting", "outcome": "Clarity", "first_feature": "Status", "constraints": None},
        "approval": {"product_brief": False, "implementation": False, "deployment": False},
        "write_lease_granted": False,
        "qualified_implementer_selected": False,
    }


class ResumeProductBriefTests(unittest.TestCase):
    def write(self, folder: Path, payload: dict) -> Path:
        path = folder / "brief.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_complete_draft_is_read_only_and_not_authorized(self):
        with tempfile.TemporaryDirectory() as td:
            result = MOD.summarize(MOD.load_draft(self.write(Path(td), draft())))
            self.assertEqual(result["missing_required"], [])
            self.assertFalse(result["implementation_authorized"])
            self.assertIn("grants no approval", result["next_action"])

    def test_missing_answer_remains_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            payload = draft(); payload["answers"]["outcome"] = ""
            result = MOD.summarize(MOD.load_draft(self.write(Path(td), payload)))
            self.assertEqual(result["missing_required"], ["outcome"])
            self.assertIn("do not begin implementation", result["next_action"])

    def test_authority_bearing_draft_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            payload = draft(); payload["approval"]["implementation"] = True
            with self.assertRaisesRegex(ValueError, "authority"):
                MOD.load_draft(self.write(Path(td), payload))

    def test_selected_implementer_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            payload = draft(); payload["qualified_implementer_selected"] = True
            with self.assertRaisesRegex(ValueError, "qualified implementer"):
                MOD.load_draft(self.write(Path(td), payload))

    def test_missing_implementer_selection_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            payload = draft(); del payload["qualified_implementer_selected"]
            with self.assertRaisesRegex(ValueError, "qualified implementer"):
                MOD.load_draft(self.write(Path(td), payload))

    def test_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td); target = self.write(folder, draft()); link = folder / "link.json"; link.symlink_to(target)
            with self.assertRaises(OSError):
                MOD.load_draft(link)

    def test_oversized_draft_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "brief.json"
            path.write_bytes(b"{" + b" " * MOD.MAX_BYTES + b"}")
            with self.assertRaisesRegex(ValueError, "no larger"):
                MOD.load_draft(path)


if __name__ == "__main__":
    unittest.main()
