"""Reject symlink-based bootstrap escapes before and during installation."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("bootstrap", ROOT / "scripts" / "bootstrap.py")
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class BootstrapPathSecurityTests(unittest.TestCase):
    def test_symlink_parent_is_rejected_before_any_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            target = base / "target"
            outside = base / "outside"
            target.mkdir()
            outside.mkdir()
            try:
                (target / "docs").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("test environment cannot create symlinks")
            with self.assertRaises(FileExistsError):
                bootstrap.preflight_copy_paths(target)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((target / ".onecompany").exists())

    def test_descriptor_copy_cannot_follow_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            target = base / "target"
            outside = base / "outside"
            target.mkdir()
            outside.mkdir()
            try:
                (target / "docs").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("test environment cannot create symlinks")
            with self.assertRaises((OSError, ValueError)):
                bootstrap.copy_item(
                    ROOT / "README.md", target / "docs" / "escape.md",
                    False, target,
                )
            self.assertFalse((outside / "escape.md").exists())

    def test_descriptor_copy_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            existing = target / "keep.md"
            existing.write_text("project owned\\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                bootstrap.copy_item(ROOT / "README.md", existing, False, target)
            self.assertEqual(existing.read_text(encoding="utf-8"), "project owned\\n")


if __name__ == "__main__":
    unittest.main()
