"""Source checkout identity must not depend on a mutable Git remote."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import onboard

SPEC = importlib.util.spec_from_file_location(
    "first_run_wizard_source_guard", ROOT / "scripts" / "first_run_wizard.py")
SOURCE_ONLY = SPEC.origin is not None and Path(SPEC.origin).is_file()
if SOURCE_ONLY:
    wizard = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(wizard)
else:
    wizard = None

SOURCE_CONFIG = ROOT / ".onecompany" / "config.json"
SOURCE_INSTALLATION = (
    SOURCE_CONFIG.is_file()
    and json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    .get("project", {}).get("repository") == "NTinkicht/OneCompany"
)


@unittest.skipUnless(SOURCE_ONLY and SOURCE_INSTALLATION,
                     "OneCompany source-only identity guard; installed target is not source")
class SourceCheckoutIdentityTests(unittest.TestCase):
    """Run the real discovery and wizard without changing remote configuration."""

    def test_no_origin_or_changed_origin_still_source(self):
        """A removed/renamed remote cannot turn the source into an Adopt target."""
        for observed_remote in (None, "NTinkicht/Unrelated", "elsewhere/fork",
                                "NTinkicht/OneCompany"):
            with self.subTest(observed_remote=observed_remote):
                with mock.patch.object(onboard, "infer_repo", return_value=observed_remote):
                    mode, configured = onboard.detect_mode(ROOT)
                    self.assertEqual(mode, "SOURCE_REPOSITORY")
                    self.assertEqual(configured, "NTinkicht/OneCompany")
                    assessment = onboard.analyze(ROOT, repository="NTinkicht/OneCompany")
                    self.assertEqual(assessment["journey"]["path"], "blocked")
                    self.assertTrue(assessment["blockers"])
                    with self.assertRaisesRegex(ValueError, "DISCOVERY_BLOCKED"):
                        wizard.collect(
                            assessment,
                            input_fn=mock.Mock(side_effect=AssertionError("owner prompted")),
                            output_fn=mock.Mock(),
                        )

    def test_template_copy_in_other_directory_remains_adoptable(self):
        """An actual copy with source config is a template, not the source."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "template-copy"
            cfg = target / ".onecompany" / "config.json"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(json.dumps({
                "project": {"repository": "NTinkicht/OneCompany"},
            }), encoding="utf-8")
            with mock.patch.object(onboard, "infer_repo", return_value=None):
                mode, configured = onboard.detect_mode(target)
                self.assertEqual(mode, "TEMPLATE_COPY")
                self.assertEqual(configured, "NTinkicht/OneCompany")
                assessment = onboard.analyze(target, repository="NTinkicht/my-new-app")
                self.assertEqual(assessment["journey"]["path"], "adopt")
                self.assertEqual(assessment["mode"], "TEMPLATE_COPY")

    def test_actual_copied_module_detects_template_without_source_root(self):
        """A standalone template uses its OWN module and still offers Adopt."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "copied-template"
            scripts = target / "scripts"
            scripts.mkdir(parents=True)
            for name in ("onboard.py", "onecompany_lib.py"):
                shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            config = target / ".onecompany" / "config.json"
            config.parent.mkdir()
            config.write_text(json.dumps({
                "project": {"repository": "NTinkicht/OneCompany"},
            }), encoding="utf-8")
            # Match smoke_init.py: the copied tree gets its own fresh Git
            # repository BEFORE OneCompany init updates the source config.
            initialized = subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=target, text=True, capture_output=True, timeout=12,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            self.assertIsNone(onboard.git(target, "ls-files", "--error-unmatch", "--",
                                         ".onecompany/config.json"))
            code = (
                "import json, onboard; from pathlib import Path; "
                "print(json.dumps({'root': str(onboard.ROOT), "
                "'mode': onboard.detect_mode(Path('.').resolve())[0]}))"
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = str(scripts)
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=target, env=env, text=True, capture_output=True, timeout=12,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            observed = json.loads(result.stdout)
            self.assertEqual(observed["root"], str(target))
            self.assertEqual(observed["mode"], "TEMPLATE_COPY")
            # Merely staging source-looking configuration must not confer
            # source identity (nor should committing the copied template).
            stage = subprocess.run(
                ["git", "add", ".onecompany/config.json"],
                cwd=target, text=True, capture_output=True, timeout=12,
            )
            self.assertEqual(stage.returncode, 0, stage.stderr)
            staged = subprocess.run(
                [sys.executable, "-c", code],
                cwd=target, env=env, text=True, capture_output=True, timeout=12,
            )
            self.assertEqual(staged.returncode, 0, staged.stderr)
            self.assertEqual(json.loads(staged.stdout)["mode"], "TEMPLATE_COPY")
            committed = subprocess.run(
                ["git", "-c", "user.name=Test Reviewer",
                 "-c", "user.email=test@example.invalid",
                 "commit", "-m", "template first commit"],
                cwd=target, text=True, capture_output=True, timeout=12,
            )
            self.assertEqual(committed.returncode, 0, committed.stderr)
            adopted = subprocess.run(
                [sys.executable, "-c", code],
                cwd=target, env=env, text=True, capture_output=True, timeout=12,
            )
            self.assertEqual(adopted.returncode, 0, adopted.stderr)
            self.assertEqual(json.loads(adopted.stdout)["mode"], "TEMPLATE_COPY")

    def test_shallow_template_copy_is_not_source(self):
        """A shallow customer/template repo must not gain source identity."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "shallow-copy"
            scripts = target / "scripts"
            scripts.mkdir(parents=True)
            for name in ("onboard.py", "onecompany_lib.py"):
                shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            cfg = target / ".onecompany" / "config.json"
            cfg.parent.mkdir()
            cfg.write_text(json.dumps({
                "project": {"repository": "NTinkicht/OneCompany"},
            }), encoding="utf-8")
            subprocess.run(["git", "init", "-b", "main"], cwd=target,
                           check=True, capture_output=True, text=True)
            subprocess.run(["git", "add", "."], cwd=target,
                           check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=Test Reviewer",
                 "-c", "user.email=test@example.invalid",
                 "commit", "-m", "template"],
                cwd=target, check=True, capture_output=True, text=True,
            )
            # A shallow boundary without the immutable OneCompany root commit
            # cannot prove source identity.
            subprocess.run(["git", "rev-parse", "--is-shallow-repository"],
                           cwd=target, check=True, capture_output=True, text=True)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(scripts)
            code = ("import onboard; from pathlib import Path; "
                    "print(onboard.detect_mode(Path('.').resolve())[0])")
            result = subprocess.run([sys.executable, "-c", code], cwd=target,
                                    env=env, text=True, capture_output=True,
                                    timeout=12)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "TEMPLATE_COPY")

    def test_git_helper_scrubs_repository_location_environment(self):
        """Inherited Git location variables cannot redirect identity checks."""
        with mock.patch.dict(os.environ, {
            "GIT_DIR": "/definitely/not/the/repo",
            "GIT_WORK_TREE": "/also/not/the/repo",
            "GIT_INDEX_FILE": "/tmp/not-an-index",
        }):
            self.assertIsNotNone(onboard.git(ROOT, "rev-parse", "--show-toplevel"))

    def test_no_source_paths_mutated(self):
        """A source-discovery read must not touch local project or remotes."""
        source = ROOT / "scripts" / "onboard.py"
        before = source.read_bytes()
        with mock.patch.object(onboard, "infer_repo", return_value=None):
            report = onboard.analyze(ROOT, repository="NTinkicht/OneCompany")
        self.assertIn("source repository cannot be onboarded", " ".join(report["blockers"]))
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
