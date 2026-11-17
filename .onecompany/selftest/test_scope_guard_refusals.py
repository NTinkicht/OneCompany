"""Exact-reason fail-closed coverage for scripts/scope_guard.py (OC-P0-10, #558)."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import scope_guard  # noqa: E402
from scope_guard import scope_covers_path, scope_errors, undeclared_paths  # noqa: E402


def proc(code=0, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=out, stderr=err)


class UnsafePathTests(unittest.TestCase):
    def test_positive_control_safe_pair_is_covered(self):
        self.assertTrue(scope_covers_path("src/auth", "src/auth/a.py"))

    def test_parent_traversal_path_never_covered(self):
        self.assertFalse(scope_covers_path("src", "src/../.github/workflows/ci.yml"))
        self.assertFalse(scope_covers_path("**", "../outside.txt"))

    def test_parent_traversal_scope_never_covers(self):
        self.assertFalse(scope_covers_path("src/../.github", ".github/workflows/ci.yml"))

    def test_dot_and_empty_segments_rejected(self):
        for bad in ("src/./a.py", "src//a.py"):
            self.assertFalse(scope_covers_path("src", bad), bad)
            self.assertFalse(scope_covers_path(bad, "src/a.py"), bad)

    def test_nul_byte_rejected(self):
        self.assertFalse(scope_covers_path("src", "src/a\x00.py"))
        self.assertFalse(scope_covers_path("src\x00", "src/a.py"))

    def test_empty_scope_or_path_rejected(self):
        for empty in ("", "   ", "/", "./"):
            self.assertFalse(scope_covers_path(empty, "src/a.py"), repr(empty))
            self.assertFalse(scope_covers_path("src", empty), repr(empty))

    def test_dotfile_anchor_not_aliased_to_plain_name(self):
        self.assertFalse(scope_covers_path("github", ".github/workflows/ci.yml"))
        self.assertFalse(scope_covers_path(".github", "github/workflows/ci.yml"))
        self.assertTrue(scope_covers_path(".github", ".github/workflows/ci.yml"))

    def test_leading_anchor_and_backslash_normalised(self):
        self.assertTrue(scope_covers_path("./src/", "/src\\a.py"))

    def test_catch_all_scopes_cover_safe_paths(self):
        for star in ("*", "**", "**/*"):
            self.assertTrue(scope_covers_path(star, "a/b/c.py"), star)


class UndeclaredPathTests(unittest.TestCase):
    def test_empty_scope_makes_every_path_undeclared(self):
        self.assertEqual(undeclared_paths(["b.py", "a.py", "a.py"], []), ["a.py", "b.py"])
        self.assertEqual(undeclared_paths(["a.py"], ["", "  "]), ["a.py"])

    def test_positive_control_in_scope_paths_not_reported(self):
        self.assertEqual(undeclared_paths(["src/a.py"], ["src"]), [])


class ScopeErrorsTests(unittest.TestCase):
    def test_unresolved_work_unit_refused(self):
        for wu in (None, "WU-X", ["x"]):
            self.assertEqual(
                scope_errors(["a.py"], wu),
                ["work unit could not be resolved for live PR scope verification"],
            )

    def test_missing_empty_or_non_list_write_scope_refused(self):
        expected = ["work unit has no declared write_scope; exact live scope cannot be verified"]
        for wu in ({}, {"write_scope": []}, {"write_scope": "src"}, {"write_scope": None}):
            self.assertEqual(scope_errors(["a.py"], wu), expected)

    def test_off_scope_paths_reported_sorted(self):
        self.assertEqual(
            scope_errors(["src/a.py", "z.txt", ".github/x.yml"], {"write_scope": ["src"]}),
            ["live PR modifies paths outside declared write_scope: .github/x.yml, z.txt"],
        )

    def test_positive_control_in_scope_diff_passes(self):
        self.assertEqual(scope_errors(["src/a.py", "src/b/c.py"], {"write_scope": ["src"]}), [])


class GhFailureTests(unittest.TestCase):
    def test_changed_files_nonzero_exit_returns_stderr(self):
        with mock.patch.object(scope_guard, "run", return_value=proc(1, "", " boom ")):
            self.assertEqual(scope_guard.changed_files("o/r", 1), (None, "boom"))

    def test_changed_files_nonzero_exit_without_output(self):
        with mock.patch.object(scope_guard, "run", return_value=proc(1)):
            self.assertEqual(scope_guard.changed_files("o/r", 1), (None, "unknown diff error"))

    def test_changed_files_positive_control_strips_blank_lines(self):
        with mock.patch.object(scope_guard, "run", return_value=proc(0, "a.py\n\n b.py \n")):
            self.assertEqual(scope_guard.changed_files("o/r", 1), (["a.py", "b.py"], None))

    def test_live_pr_nonzero_exit_fails_closed(self):
        with mock.patch.object(scope_guard, "run", return_value=proc(1, "", "nope")):
            self.assertEqual(scope_guard.live_pr("o/r", 1), (None, "nope"))
        with mock.patch.object(scope_guard, "run", return_value=proc(1)):
            self.assertEqual(scope_guard.live_pr("o/r", 1), (None, "cannot read live PR"))

    def test_live_pr_invalid_json_fails_closed(self):
        with mock.patch.object(scope_guard, "run", return_value=proc(0, "{not json")):
            data, err = scope_guard.live_pr("o/r", 1)
        self.assertIsNone(data)
        self.assertTrue(err.startswith("invalid live PR JSON: "))

    def test_live_pr_positive_control_parses(self):
        payload = {"headRefOid": "a" * 40, "state": "OPEN"}
        with mock.patch.object(scope_guard, "run", return_value=proc(0, json.dumps(payload))):
            self.assertEqual(scope_guard.live_pr("o/r", 1), (payload, None))


if __name__ == "__main__":
    unittest.main()
