"""Source checkout identity must not depend on a mutable Git remote."""
from __future__ import annotations

import importlib.util
import json
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
