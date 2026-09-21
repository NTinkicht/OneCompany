from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import product_brief as brief


class ProductBriefTests(unittest.TestCase):
    def target(self, root: Path) -> Path:
        target = root / "future-product"
        return target

    def answers(self) -> dict[str, str]:
        return {
            "audience": "Families",
            "problem": "They need a simple overview",
            "outcome": "Review the family checklist",
            "first_feature": "A local checklist",
            "constraints": "No sensitive records",
        }

    def test_owner_fields_are_editable_but_never_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.target(Path(tmp))
            self.assertFalse(target.exists())
            assessment = brief.analyze(target, repository="demo/future-product")
            draft = brief.make_draft(assessment, self.answers())
            self.assertEqual(draft["project"]["path"], "create")
            self.assertEqual(draft["answers"]["audience"], "Families")
            self.assertEqual(draft["missing_required_answers"], [])
            self.assertEqual(draft["acceptance_criteria"], [])
            self.assertEqual(draft["status"], "DRAFT_NOT_APPROVED")
            self.assertEqual(draft["approval"],
                             {"product_brief": False,
                              "implementation": False, "deployment": False})
            self.assertFalse(draft["write_lease_granted"])
            self.assertFalse(draft["qualified_implementer_selected"])
            self.assertFalse(target.exists())

    def test_adopt_facts_are_preserved_and_unknown_intent_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.target(Path(tmp))
            target.mkdir()
            (target / "pyproject.toml").write_text("[project]\nname='demo'\n")
            assessment = brief.analyze(target, repository="demo/future-product")
            draft = brief.make_draft(assessment, {})
            self.assertEqual(draft["project"]["path"], "adopt")
            self.assertIn("Python", draft["project"]["known_stack"])
            self.assertEqual(draft["missing_required_answers"],
                             list(brief.REQUIRED))
            self.assertTrue(all(draft["answers"][x] is None
                                for x in brief.REQUIRED))
            self.assertFalse((target / ".onecompany").exists())

    def test_save_is_explicit_exclusive_and_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = self.target(root)
            report = brief.analyze(target, repository="demo/future-product")
            draft = brief.make_draft(report, self.answers())
            exported = root / "brief.json"
            brief.save_exclusive(exported, draft)
            self.assertEqual(json.loads(exported.read_text())["answers"]["problem"],
                             self.answers()["problem"])
            self.assertEqual(exported.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                brief.save_exclusive(exported, draft)
            self.assertFalse(target.exists())

    def test_existing_file_and_symlink_destination_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = brief.make_draft(
                brief.analyze(self.target(root), repository="demo/future-product"),
                self.answers(),
            )
            victim = root / "victim.json"
            victim.write_text("keep")
            path = root / "brief.json"
            path.symlink_to(victim)
            with self.assertRaises(FileExistsError):
                brief.save_exclusive(path, draft)
            self.assertEqual(victim.read_text(), "keep")
            with self.assertRaises((ValueError, OSError)):
                brief.save_exclusive(root / "missing" / "brief.json", draft)
            self.assertFalse((root / "missing").exists())

    def test_intermediate_symlink_parent_does_not_escape_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = brief.make_draft(
                brief.analyze(self.target(root), repository="demo/future-product"),
                self.answers(),
            )
            real_parent = root / "real"
            real_parent.mkdir()
            shortcut = root / "shortcut"
            shortcut.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises(OSError):
                brief.save_exclusive(shortcut / "draft.json", draft)
            self.assertFalse((real_parent / "draft.json").exists())
            nested = root / "nested"
            nested.mkdir()
            (nested / "bad").symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises(OSError):
                brief.save_exclusive(nested / "bad" / "draft.json", draft)
            self.assertFalse((real_parent / "draft.json").exists())

    def test_incomplete_cli_refuses_save_and_no_target_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = self.target(root)
            result = brief.main([
                "--target", str(target), "--repository", "demo/future-product",
                "--save-to", str(root / "brief.json"), "--audience", "Families",
            ])
            self.assertEqual(result, 2)
            self.assertFalse((root / "brief.json").exists())
            self.assertFalse(target.exists())

    def test_control_codes_and_long_answers_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.target(Path(tmp))
            assessment = brief.analyze(target, repository="demo/future-product")
            for invalid in ("a" * 401, "test\x00value", "test\x1bvalue"):
                with self.subTest(invalid=repr(invalid[:20])):
                    with self.assertRaises(ValueError):
                        brief.make_draft(
                            assessment, {**self.answers(), "audience": invalid}
                        )


if __name__ == "__main__":
    unittest.main()
