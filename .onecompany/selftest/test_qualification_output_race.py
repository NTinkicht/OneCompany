from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import qualification  # noqa: E402


@unittest.skipUnless(
    hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd,
    "secure descriptor-relative output traversal requires POSIX dir_fd support",
)
class QualificationOutputRaceTests(unittest.TestCase):
    def test_normal_output_create_and_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            artifact_root = repo_root / ".onecompany-evidence" / "qualification"
            target = artifact_root / "run" / "result.json"
            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
            ):
                qualification._write_or_print({"value": 1}, target)
                self.assertIn('"value": 1', target.read_text(encoding="utf-8"))
                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    "already exists",
                ):
                    qualification._write_or_print({"value": 2}, target)
                qualification._write_or_print(
                    {"value": 3},
                    target,
                    overwrite=True,
                )
                self.assertIn('"value": 3', target.read_text(encoding="utf-8"))

    def test_final_component_symlink_cannot_overwrite_control_plane(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            control = repo_root / ".onecompany" / "config.json"
            control.parent.mkdir(parents=True)
            control.write_text("protected\n", encoding="utf-8")
            artifact_root = repo_root / ".onecompany-evidence" / "qualification"
            artifact_root.mkdir(parents=True)
            target = artifact_root / "result.json"
            target.symlink_to(control)
            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
            ):
                with self.assertRaises(qualification.QualificationInputError):
                    qualification._write_or_print(
                        {"safe": False},
                        target,
                        overwrite=True,
                    )
            self.assertEqual(control.read_text(encoding="utf-8"), "protected\n")

    def test_symlinked_artifact_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            control_dir = repo_root / ".onecompany"
            control_dir.mkdir(parents=True)
            protected = control_dir / "config.json"
            protected.write_text("protected\n", encoding="utf-8")
            evidence_parent = repo_root / ".onecompany-evidence"
            evidence_parent.mkdir()
            artifact_root = evidence_parent / "qualification"
            artifact_root.symlink_to(control_dir, target_is_directory=True)
            target = artifact_root / "config.json"
            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
            ):
                with self.assertRaises(qualification.QualificationInputError):
                    qualification._write_or_print(
                        {"safe": False},
                        target,
                        overwrite=True,
                    )
            self.assertEqual(protected.read_text(encoding="utf-8"), "protected\n")

    def test_ancestor_swap_race_stays_bound_to_open_directory_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            control_dir = repo_root / ".onecompany"
            control_dir.mkdir(parents=True)
            protected = control_dir / "config.json"
            protected.write_text("protected\n", encoding="utf-8")

            artifact_root = repo_root / ".onecompany-evidence" / "qualification"
            target = artifact_root / "run" / "config.json"
            swapped = artifact_root / "run-original"
            real_open_file = qualification._open_secure_output_file
            race_triggered = False

            def racing_open_file(parent_fd, filename, *, overwrite):
                nonlocal race_triggered
                if not race_triggered:
                    race_triggered = True
                    run_dir = artifact_root / "run"
                    run_dir.rename(swapped)
                    run_dir.symlink_to(control_dir, target_is_directory=True)
                return real_open_file(parent_fd, filename, overwrite=overwrite)

            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
                patch.object(
                    qualification,
                    "_open_secure_output_file",
                    side_effect=racing_open_file,
                ),
            ):
                qualification._write_or_print(
                    {"safe": True},
                    target,
                    overwrite=True,
                )

            self.assertTrue(race_triggered)
            self.assertEqual(protected.read_text(encoding="utf-8"), "protected\n")
            self.assertIn(
                '"safe": true',
                (swapped / "config.json").read_text(encoding="utf-8"),
            )

    def test_existing_hard_link_is_rejected_before_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            control = repo_root / ".onecompany" / "config.json"
            control.parent.mkdir(parents=True)
            control.write_text("protected\n", encoding="utf-8")
            artifact_root = repo_root / ".onecompany-evidence" / "qualification"
            artifact_root.mkdir(parents=True)
            target = artifact_root / "result.json"
            os.link(control, target)

            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
            ):
                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    "multiple hard links",
                ):
                    qualification._write_or_print(
                        {"safe": False},
                        target,
                        overwrite=True,
                    )
            self.assertEqual(control.read_text(encoding="utf-8"), "protected\n")


if __name__ == "__main__":
    unittest.main()
