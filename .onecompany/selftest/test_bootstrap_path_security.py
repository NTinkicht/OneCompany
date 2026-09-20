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
                    ROOT / "onecompany.py", target / "docs" / "escape.md",
                    False, target,
                )
            self.assertFalse((outside / "escape.md").exists())

    def test_source_planning_exclusions_do_not_collide_with_target_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            for name in bootstrap.SOURCE_ONLY_PLANNING_FILES:
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("target owns this file\\n", encoding="utf-8")
                bootstrap.copy_item(ROOT / name, destination, False, target)
                self.assertEqual(destination.read_text(encoding="utf-8"), "target owns this file\\n")
            bootstrap.preflight_copy_paths(target)

    def test_recursive_docs_bootstrap_excludes_source_strategy(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            bootstrap.copy_item(ROOT / "docs", target / "docs", False, target)
            self.assertFalse((target / "docs" / "ROADMAP.md").exists())
            self.assertFalse((target / "docs" / "MASTER-EVOLUTION-ROADMAP-2026.md").exists())

    def test_descriptor_copy_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            existing = target / "keep.md"
            existing.write_text("project owned\\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                bootstrap.copy_item(ROOT / "onecompany.py", existing, False, target)
            self.assertEqual(existing.read_text(encoding="utf-8"), "project owned\\n")


if __name__ == "__main__":
    unittest.main()
