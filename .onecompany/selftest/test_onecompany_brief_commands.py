"""First-class saved-brief routes reuse real helpers without granting authority."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "onecompany.py"
HELPERS = {
    "brief-resume": "resume_product_brief.py",
    "brief-diff": "product_brief_diff.py",
    "brief-status": "brief_status.py",
    "brief-validate": "brief_validate.py",
}
AVAILABLE = ENTRY.is_file() and all((ROOT / "scripts" / h).is_file()
                                     for h in HELPERS.values())
if AVAILABLE:
    sys.path.insert(0, str(ROOT / "scripts"))
    from product_brief import make_draft
    from onboard import analyze


@unittest.skipUnless(AVAILABLE, "source-only saved-brief helpers are not installed")
class SavedBriefCommandTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ENTRY), *args], cwd=ROOT,
            capture_output=True, text=True, timeout=20,
        )

    def drafts(self, folder: Path) -> tuple[Path, Path]:
        target = folder / "new-project"
        assessment = analyze(target, repository="demo/new-project")
        answers = {
            "audience": "Families",
            "problem": "Missing appointment overview",
            "outcome": "View upcoming visits",
            "first_feature": "Simple local checklist",
            "constraints": "No personal data",
        }
        before = make_draft(assessment, answers)
        after = make_draft(assessment, {
            **answers, "outcome": "View and acknowledge upcoming visits",
        })
        first, second = folder / "first.json", folder / "second.json"
        first.write_text(json.dumps(before), encoding="utf-8")
        second.write_text(json.dumps(after), encoding="utf-8")
        self.assertFalse(target.exists())
        return first, second

    def test_all_four_real_help_routes_are_discoverable(self):
        usage = self.run_cli("--help")
        for command in HELPERS:
            with self.subTest(command=command):
                self.assertIn(command, usage.stdout)
                child = self.run_cli(command, "--help")
                self.assertEqual(child.returncode, 0, child.stderr)
                self.assertIn("usage:", child.stdout)
        self.assertIn("before", self.run_cli("brief-diff", "--help").stdout)
        self.assertIn("--require-complete", self.run_cli("brief-status", "--help").stdout)

    def test_real_draft_lifecycle_and_no_target_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first, second = self.drafts(root)
            baseline = {p: p.read_bytes() for p in (first, second)}

            resumed = self.run_cli("brief-resume", str(first), "--json")
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            resume = json.loads(resumed.stdout)
            self.assertEqual(resume["missing_required"], [])
            self.assertEqual(resume.get("status"), "DRAFT_NOT_APPROVED")
            self.assertFalse(resume.get("approved", False))

            diffed = self.run_cli("brief-diff", str(first), str(second), "--json")
            self.assertEqual(diffed.returncode, 0, diffed.stderr)
            diff = json.loads(diffed.stdout)
            self.assertEqual([item["field"] for item in diff["changed_fields"]],
                             ["outcome"])
            self.assertIs(diff["implementation_authorized"], False)

            status = self.run_cli("brief-status", str(first), "--require-complete")
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)["stage"],
                             "DRAFT_COMPLETE_NOT_APPROVED")
            self.assertIs(json.loads(status.stdout)["approved"], False)

            validated = self.run_cli("brief-validate", str(first))
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertEqual(json.loads(validated.stdout)["status"],
                             "PROPOSAL_READY_NOT_APPROVED")
            self.assertEqual({p: p.read_bytes() for p in baseline}, baseline)
            self.assertFalse((root / "new-project").exists())

    def test_missing_and_malformed_inputs_refuse_without_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            good, _ = self.drafts(root)
            bad = root / "bad.json"
            bad.write_text("{broken", encoding="utf-8")
            for command, args in (
                ("brief-resume", (str(bad),)),
                ("brief-diff", (str(good), str(bad))),
                ("brief-status", (str(bad),)),
                ("brief-validate", (str(bad),)),
            ):
                with self.subTest(command=command):
                    result = self.run_cli(command, *args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(bad.read_text(encoding="utf-8"), "{broken")
            for command in HELPERS:
                with self.subTest(command=command):
                    self.assertNotEqual(self.run_cli(command).returncode, 0)

    @unittest.skipUnless(os.name == "posix", "symlink guard requires POSIX")
    def test_symlink_is_not_followed_by_comparison_or_resume(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            good, _ = self.drafts(folder)
            link = folder / "link.json"
            link.symlink_to(good)
            for command, args in (
                ("brief-resume", (str(link),)),
                ("brief-diff", (str(good), str(link))),
            ):
                with self.subTest(command=command):
                    self.assertNotEqual(self.run_cli(command, *args).returncode, 0)

    def test_absent_helper_fails_without_attempting_child_or_target(self):
        spec = importlib.util.spec_from_file_location("brief_commands_entry", ENTRY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            for command in HELPERS:
                with self.subTest(command=command):
                    with mock.patch.object(module, "ROOT", Path(td)), \
                         mock.patch.object(module.sys, "argv", ["onecompany.py", command, "x"]), \
                         mock.patch.object(module.subprocess, "run") as run:
                        with contextlib.redirect_stdout(io.StringIO()) as output:
                            self.assertEqual(module.main(), 2)
                        self.assertIn("source checkout only", output.getvalue())
                        run.assert_not_called()

    def test_nonserver_command_preserves_child_exit_code_and_arguments(self):
        spec = importlib.util.spec_from_file_location("brief_command_entry", ENTRY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(module.sys, "argv",
                               ["onecompany.py", "brief-status", "/tmp/draft.json",
                                "--require-complete"]), \
             mock.patch.object(module.subprocess, "run",
                               return_value=mock.Mock(returncode=3)) as runner, \
             mock.patch.object(module.subprocess, "Popen") as server:
            self.assertEqual(module.main(), 3)
        self.assertEqual(runner.call_args.args[0],
                         [sys.executable, str(ROOT / "scripts" / "brief_status.py"),
                          "/tmp/draft.json", "--require-complete"])
        self.assertIs(runner.call_args.kwargs["check"], False)
        server.assert_not_called()


if __name__ == "__main__":
    unittest.main()
