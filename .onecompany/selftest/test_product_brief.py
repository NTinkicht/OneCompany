from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from product_brief import clean_answer, draft, exclusive_save  # noqa: E402
from onboard import analyze  # noqa: E402


class ProductBriefTests(unittest.TestCase):
    def test_new_project_draft_preserves_missing_intent_and_does_not_create_target(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "not-created"
            report = analyze(target, repository="owner/idea")
            result = draft(report, {})
            self.assertEqual(result["path"], "create")
            self.assertEqual(result["status"], "DRAFT_NOT_APPROVED")
            self.assertEqual(result["missing_fields"], list(("audience", "problem", "outcome", "first_feature")))
            self.assertFalse(result["approved"])
            self.assertFalse(result["application_authorized"])
            self.assertFalse(result["write_lease_granted"])
            self.assertFalse(target.exists())

    def test_adopt_preserves_known_stack_tests_ci_and_contracts(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "existing"
            (target / "tests").mkdir(parents=True)
            (target / ".github" / "workflows").mkdir(parents=True)
            (target / "package.json").write_text("{}", encoding="utf-8")
            (target / "PRODUCT.md").write_text("existing", encoding="utf-8")
            (target / ".github" / "workflows" / "ci.yml").write_text("name: CI", encoding="utf-8")
            report = analyze(target, repository="owner/real")
            result = draft(report, dict(audience="users", problem="slow intake", outcome="track work", first_feature="create item"))
            brief = result["brief"]
            self.assertEqual(result["path"], "adopt")
            self.assertEqual(result["missing_fields"], [])
            self.assertEqual(brief["known_stack"], ["Node/TypeScript"])
            self.assertEqual(brief["existing_tests"], ["tests"])
            self.assertEqual(brief["existing_ci"], ["GitHub Actions (1 workflow)"])
            self.assertIn("PRODUCT.md", brief["known_contracts"])
            self.assertFalse(brief["approved"])
            self.assertEqual((target / "PRODUCT.md").read_text(), "existing")

    def test_reject_oversized_control_chars_and_nontext(self):
        for value in ("x" * 501, "hello\\nworld", "a\\x00b"):
            with self.assertRaises(ValueError):
                clean_answer(value, "audience")
        self.assertIsNone(clean_answer("  ", "audience"))

    def test_explicit_save_private_exclusive_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "brief.json"
            value = {"approved": False, "status": "DRAFT_NOT_APPROVED"}
            exclusive_save(path, value)
            self.assertEqual(json.loads(path.read_text()), value)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                exclusive_save(path, {"approved": True})
            self.assertEqual(json.loads(path.read_text()), value)
            symlink = Path(temp) / "link.json"
            symlink.symlink_to(path)
            with self.assertRaises(FileExistsError):
                exclusive_save(symlink, {"approved": True})

    def test_cli_read_only_and_blocked_save(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "new"
            out = Path(temp) / "brief.json"
            cli = [sys.executable, str(ROOT / "onecompany.py"), "brief", "--target", str(target), "--repository", "owner/new", "--json"]
            result = subprocess.run(cli, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(target.exists())
            self.assertFalse(out.exists())
            parsed = json.loads(result.stdout)
            self.assertFalse(parsed["approved"])
            self.assertIsNone(parsed["brief"]["problem"])
            saved = subprocess.run(cli + ["--save-to", str(out)], cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.assertTrue(out.exists())
            again = subprocess.run(cli + ["--save-to", str(out)], cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(again.returncode, 2)
            self.assertFalse(target.exists())
            blocked = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "brief", "--target", str(target), "--save-to", str(Path(temp) / "bad.json")], cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(blocked.returncode, 2)
            self.assertFalse((Path(temp) / "bad.json").exists())


if __name__ == "__main__":
    unittest.main()
