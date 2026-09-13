from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from scope_guard import scope_covers_path, undeclared_paths
from planning_lib import scopes_overlap


class ScopeGuardTests(unittest.TestCase):
    def test_directory_scope_covers_nested_file(self):
        self.assertTrue(scope_covers_path("src/auth", "src/auth/service.py"))

    def test_glob_scope_covers_nested_file(self):
        self.assertTrue(scope_covers_path("src/auth/**", "src/auth/service.py"))

    def test_neighbor_directory_is_not_covered(self):
        self.assertFalse(scope_covers_path("src/auth", "src/authorization/service.py"))

    def test_undeclared_file_is_detected(self):
        self.assertEqual(undeclared_paths(["src/auth/a.py", ".github/workflows/ci.yml"], ["src/auth/**"]), [".github/workflows/ci.yml"])

    def test_directory_and_child_file_overlap(self):
        self.assertTrue(scopes_overlap("src/auth", "src/auth/service.py"))

    def test_disjoint_scopes_do_not_overlap(self):
        self.assertFalse(scopes_overlap("src/auth/**", "web/marketing/**"))


if __name__ == "__main__":
    unittest.main()
