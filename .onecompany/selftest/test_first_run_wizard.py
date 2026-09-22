"""Source-checkout first-run wizard must preserve owner sovereignty and existing assets."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "onecompany.py"
WIZARD = ROOT / "scripts" / "first_run_wizard.py"
SOURCE_ONLY = ENTRY.is_file() and WIZARD.is_file()


@unittest.skipUnless(SOURCE_ONLY, "source-only first-run wizard not installed in target")
class FirstRunWizardTests(unittest.TestCase):
    """Exercise real CLI and secure draft persistence, not synthetic success."""

    def run_start(self, target, *opts, answers=None):
        """Run the actual top-level router with bounded owner stdin."""
        return subprocess.run(
            [sys.executable, str(ENTRY), "start", "--target", str(target),
             "--repository", "NTinkicht/disposable", *opts],
            cwd=ROOT, text=True, input=answers, capture_output=True, timeout=15,
        )

    def test_create_draft_is_read_only_without_save(self):
        """An explicit new repo path must remain uncreated after a complete chat."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "new-project"
            answers = "Students\\nNeed a checklist\\nTrack work\\nAdd task\\nNo private data\\n".replace("\\n", "\n")
            result = self.run_start(target, answers=answers)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Create your project", result.stdout)
            self.assertIn("NOT approved", result.stdout)
            self.assertIn("nothing saved", result.stdout)
            self.assertFalse(target.exists())

    def test_adopt_preserves_existing_data_and_discovers_files(self):
        """Adopt displays real stack/tests/CI without altering the source repo."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            readme = target / "README.md"
            readme.write_text("customer-owned", encoding="utf-8")
            (target / "package.json").write_text("{}", encoding="utf-8")
            (target / "tests").mkdir()
            before = [(p.name, p.stat().st_mtime_ns) for p in target.iterdir()]
            answers = "Editors\\nHard workflow\\nShip a draft\\nFirst screen\\nPrivacy\\n".replace("\\n", "\n")
            result = self.run_start(target, answers=answers)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Adopt your project", result.stdout)
            self.assertIn("Node/TypeScript", result.stdout)
            self.assertIn("tests", result.stdout)
            self.assertEqual(readme.read_text(), "customer-owned")
            self.assertEqual(before, [(p.name, p.stat().st_mtime_ns) for p in target.iterdir()])

    @unittest.skipUnless(os.name == "posix", "secure draft export requires POSIX dir_fd")
    def test_explicit_save_is_private_canonical_unapproved_draft(self):
        """Save uses existing Product Brief exporter with a new 0600 JSON file."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "owner-brief.json"
            answers = "Parents\\nScheduling\\nSee sessions\\nCreate reminder\\nNo PII\\n".replace("\\n", "\n")
            result = self.run_start(Path(tmp) / "brand-new", "--save-to", str(path), answers=answers)
            self.assertEqual(result.returncode, 0, result.stderr)
            draft = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(draft["status"], "DRAFT_NOT_APPROVED")
            self.assertEqual(draft["answers"]["audience"], "Parents")
            self.assertEqual(draft["missing_required_answers"], [])
            self.assertFalse(draft["approval"]["implementation"])
            self.assertFalse(draft["write_lease_granted"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            again = self.run_start(Path(tmp) / "brand-new", "--save-to", str(path), answers=answers)
            self.assertEqual(again.returncode, 2)
            self.assertEqual(json.loads(path.read_text())["answers"]["audience"], "Parents")
            self.assertIn("REFUSED:", again.stderr)

    def test_missing_required_answer_or_eof_refuses_no_save(self):
        """Incomplete or interrupted owner input cannot produce authority or files."""
        with tempfile.TemporaryDirectory() as tmp:
            for answers in ("Someone\n\nResult\nFeature\nLimits\n", "Only one answer\n"):
                with self.subTest(answers=answers):
                    path = Path(tmp) / "incomplete.json"
                    result = self.run_start(Path(tmp) / "new", "--save-to", str(path), answers=answers)
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(path.exists())
                    self.assertIn("REFUSED:", result.stderr)

    def test_source_repository_refuses_before_prompts(self):
        """The OneCompany framework must not onboard itself as a customer target."""
        config = json.loads((ROOT / ".onecompany" / "config.json").read_text())
        if config.get("project", {}).get("repository") != "NTinkicht/OneCompany":
            self.skipTest("installed target is correctly allowed to start the wizard")
        result = self.run_start(ROOT, answers="A\nB\nC\nD\nE\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("DISCOVERY_BLOCKED", result.stderr)

    def test_unknown_option_refuses(self):
        """An unsupported --apply or --approve option never changes the project."""
        with tempfile.TemporaryDirectory() as tmp:
            for option in ("--apply", "--approve"):
                result = self.run_start(Path(tmp) / "new", option, answers="A\nB\nC\nD\nE\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unrecognized arguments", result.stderr)


if __name__ == "__main__":
    unittest.main()
