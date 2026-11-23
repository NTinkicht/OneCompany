import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REV = "1" * 40
D = {"a": "a" * 64, "b": "b" * 64}


def entry(eid, vp, theme, digest="a"):
    return {"id": eid, "viewport": vp, "theme": theme, "sha256": digest * 64}


def matrix(ids=("home",), vps=(320, 1024), themes=("light", "dark"), digest="a"):
    return [entry(i, v, t, digest) for i in ids for v in vps for t in themes]


class VisualGoldenCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, goldens, captures, *extra, vps=(320, 1024), themes=("light", "dark"), raw=None):
        g = self.tmp / "g.json"
        c = self.tmp / "c.json"
        g.write_text(raw if raw is not None else json.dumps(
            {"revision": REV, "viewports": list(vps), "themes": list(themes), "goldens": goldens}), encoding="utf-8")
        c.write_text(json.dumps({"revision": "2" * 40, "captures": captures}), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "visual_golden_check.py"), str(g), str(c), *extra],
                              capture_output=True, text=True)

    def test_identical_complete_matrix_passes(self):
        r = self.run_cli(matrix(("home", "login")), matrix(("home", "login")))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_changed_digest_fails(self):
        r = self.run_cli(matrix(), matrix(digest="b"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("CHANGED home 320 dark", r.stdout)

    def test_missing_capture_fails(self):
        r = self.run_cli(matrix(), matrix()[:-1])
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISSING home 1024 dark", r.stdout)

    def test_unexpected_capture_fails(self):
        r = self.run_cli(matrix(), matrix(("home", "extra")))
        self.assertEqual(r.returncode, 1)
        self.assertIn("UNEXPECTED extra 320 light", r.stdout)

    def test_incomplete_golden_matrix_fails_even_if_captures_match(self):
        partial = matrix()[:-1]
        r = self.run_cli(partial, partial)
        self.assertEqual(r.returncode, 1)
        self.assertIn("INCOMPLETE_MATRIX home 1024 dark", r.stdout)

    def test_json_output_is_deterministic(self):
        r = self.run_cli(matrix(), matrix(digest="b"), "--json")
        out = json.loads(r.stdout)
        self.assertEqual(len(out["changed"]), 4)
        self.assertEqual(out["missing"], [])

    def test_undeclared_viewport_or_theme_is_unable_to_verify(self):
        self.assertEqual(self.run_cli(matrix(), matrix() + [entry("home", 768, "light")]).returncode, 2)
        self.assertEqual(self.run_cli(matrix(), matrix() + [entry("home", 320, "sepia")]).returncode, 2)

    def test_bad_digest_duplicate_and_empty_are_unable_to_verify(self):
        bad = matrix()
        bad[0]["sha256"] = "XYZ"
        self.assertEqual(self.run_cli(bad, matrix()).returncode, 2)
        self.assertEqual(self.run_cli(matrix(), matrix() + matrix()[:1]).returncode, 2)
        self.assertEqual(self.run_cli([], matrix()).returncode, 2)
        self.assertEqual(self.run_cli(matrix(), []).returncode, 2)

    def test_bad_revision_and_malformed_files_are_unable_to_verify(self):
        r = self.run_cli(matrix(), matrix(), raw=json.dumps(
            {"revision": "abc", "viewports": [320], "themes": ["light"], "goldens": matrix()}))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.run_cli(matrix(), matrix(), raw="not json").returncode, 2)
        self.assertEqual(self.run_cli(matrix(), matrix(), vps=(320, 320)).returncode, 2)
        self.assertEqual(self.run_cli(matrix(), matrix(), vps=(0,)).returncode, 2)
        self.assertEqual(self.run_cli(matrix(), matrix(), themes=()).returncode, 2)


    def test_duplicate_key_is_refused_not_last_wins(self):
        good = json.dumps(matrix())
        hdr = '"revision": "%s", "viewports": [320, 1024], "themes": ["light", "dark"]' % REV
        dups = [
            '{%s, "goldens": %s, "goldens": %s}' % (hdr, json.dumps(matrix(digest="b")), good),
            '{%s, "revision": "%s", "goldens": %s}' % (hdr, "2" * 40, good),
            '{%s, "goldens": [{"id": "x", "id": "home", "viewport": 320, "theme": "light", "sha256": "%s"}]}' % (hdr, "a" * 64),
        ]
        self.assertEqual(self.run_cli(matrix(), matrix()).returncode, 0)
        for body in dups:
            r = self.run_cli(matrix(), matrix(), raw=body)
            self.assertEqual(r.returncode, 2, body)
            self.assertIn("UNABLE TO VERIFY", r.stderr)
            self.assertIn("unreadable", r.stderr)
            self.assertNotIn("Traceback", r.stderr)
        c = self.tmp / "c2.json"
        c.write_text('{"revision": "%s", "captures": %s, "captures": []}' % ("2" * 40, good), encoding="utf-8")
        g = self.tmp / "g.json"
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "visual_golden_check.py"), str(g), str(c)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("unreadable", r.stderr)


if __name__ == "__main__":
    unittest.main()
