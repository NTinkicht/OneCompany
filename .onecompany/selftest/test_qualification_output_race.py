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
            real_atomic_replace = qualification._atomic_replace_output
            race_triggered = False

            def racing_atomic_replace(parent_fd, filename, text):
                nonlocal race_triggered
                if not race_triggered:
                    race_triggered = True
                    run_dir = artifact_root / "run"
                    run_dir.rename(swapped)
                    run_dir.symlink_to(control_dir, target_is_directory=True)
                return real_atomic_replace(parent_fd, filename, text)

            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
                patch.object(
                    qualification,
                    "_atomic_replace_output",
                    side_effect=racing_atomic_replace,
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

    def test_existing_hard_link_is_rejected_before_overwrite(self):
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

    def test_late_hard_link_after_validation_is_replaced_not_truncated(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            control = repo_root / ".onecompany" / "config.json"
            control.parent.mkdir(parents=True)
            control.write_text("protected\n", encoding="utf-8")
            artifact_root = repo_root / ".onecompany-evidence" / "qualification"
            artifact_root.mkdir(parents=True)
            target = artifact_root / "result.json"
            real_validate = qualification._validate_existing_output_entry
            injected = False

            def validate_then_link(parent_fd, filename):
                nonlocal injected
                real_validate(parent_fd, filename)
                if not injected:
                    injected = True
                    os.link(control, target)

            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
                patch.object(
                    qualification,
                    "_validate_existing_output_entry",
                    side_effect=validate_then_link,
                ),
            ):
                qualification._write_or_print(
                    {"safe": True},
                    target,
                    overwrite=True,
                )

            self.assertTrue(injected)
            self.assertEqual(control.read_text(encoding="utf-8"), "protected\n")
            self.assertIn('"safe": true', target.read_text(encoding="utf-8"))
            self.assertNotEqual(os.stat(control).st_ino, os.stat(target).st_ino)

    def test_temp_hard_link_injected_after_initial_validation_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            artifact_root = repo_root / ".onecompany-evidence" / "qualification"
            artifact_root.mkdir(parents=True)
            target = artifact_root / "result.json"
            target.write_text("original\n", encoding="utf-8")
            leak = artifact_root / "leak.json"
            real_write = qualification._write_open_fd
            injected = False

            def write_then_link(fd, text):
                nonlocal injected
                real_write(fd, text)
                temp_candidates = list(artifact_root.glob(".result.json.tmp-*"))
                self.assertEqual(len(temp_candidates), 1)
                os.link(temp_candidates[0], leak)
                injected = True

            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
                patch.object(
                    qualification,
                    "_write_open_fd",
                    side_effect=write_then_link,
                ),
            ):
                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    "multiply linked or changed before publish",
                ):
                    qualification._write_or_print(
                        {"safe": True},
                        target,
                        overwrite=True,
                    )

            self.assertTrue(injected)
            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")
            self.assertTrue(leak.exists())
            self.assertEqual(list(artifact_root.glob(".result.json.tmp-*")), [])

    def test_replacement_write_failure_preserves_error_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            artifact_root = repo_root / ".onecompany-evidence" / "qualification"
            artifact_root.mkdir(parents=True)
            target = artifact_root / "result.json"
            target.write_text("original\n", encoding="utf-8")

            def close_then_fail(fd, _text):
                os.close(fd)
                raise qualification.QualificationInputError("simulated replacement write failure")

            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
                patch.object(
                    qualification,
                    "_write_open_fd",
                    side_effect=close_then_fail,
                ),
            ):
                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    "simulated replacement write failure",
                ):
                    qualification._write_or_print(
                        {"safe": True},
                        target,
                        overwrite=True,
                    )

            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(list(artifact_root.glob(".result.json.tmp-*")), [])


if __name__ == "__main__":
    unittest.main()
