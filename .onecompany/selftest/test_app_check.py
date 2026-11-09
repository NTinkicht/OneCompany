import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import app_check  # noqa: E402

REV = "1" * 40


def full(**over):
    rows = []
    for s in app_check.SCREENS:
        for v in app_check.VIEWPORTS:
            for t in app_check.STATES:
                row = {"screen": s, "viewport": v, "state": t, "keyboard_ok": True, "a11y_serious": 0,
                       "completion_claimed": False, "completion_evidence_sha256": None}
                rows.append(row)
    return rows


class AppCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, rows=None, raw=None, revision=REV):
        p = self.tmp / "e.json"
        p.write_text(raw if raw is not None else json.dumps({"revision": revision, "evidence": rows}), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "app_check.py"), str(p)],
                              capture_output=True, text=True)

    def test_complete_matrix_passes(self):
        r = self.run_cli(full())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("160 entries", r.stdout)

    def test_missing_cell_fails(self):
        r = self.run_cli(full()[:-1])
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISSING mission-control 1440 slow", r.stdout)

    def test_unexpected_cell_fails(self):
        rows = full() + [dict(full()[0], screen="admin")]
        r = self.run_cli(rows)
        self.assertEqual(r.returncode, 1)
        self.assertIn("UNEXPECTED admin 320 ready", r.stdout)

    def test_keyboard_failure_fails(self):
        rows = full()
        rows[0]["keyboard_ok"] = False
        r = self.run_cli(rows)
        self.assertEqual(r.returncode, 1)
        self.assertIn("KEYBOARD welcome 320 ready", r.stdout)

    def test_serious_a11y_fails(self):
        rows = full()
        rows[1]["a11y_serious"] = 2
        r = self.run_cli(rows)
        self.assertEqual(r.returncode, 1)
        self.assertIn("A11Y welcome 320 empty", r.stdout)

    def test_completion_without_evidence_fails_and_with_evidence_passes(self):
        rows = full()
        rows[2]["completion_claimed"] = True
        r = self.run_cli(rows)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FICTIONAL_COMPLETION welcome 320 error", r.stdout)
        rows[2]["completion_evidence_sha256"] = "a" * 64
        self.assertEqual(self.run_cli(rows).returncode, 0)
        rows[2]["completion_evidence_sha256"] = "short"
        self.assertEqual(self.run_cli(rows).returncode, 1)

    def test_malformed_input_is_unable_to_verify(self):
        bad_a = full(); bad_a[0]["a11y_serious"] = True
        bad_k = full(); bad_k[0]["keyboard_ok"] = "yes"
        bad_v = full(); bad_v[0]["viewport"] = True
        dup = full() + [full()[0]]
        for rows in (bad_a, bad_k, bad_v, dup, []):
            self.assertEqual(self.run_cli(rows).returncode, 2)
        self.assertEqual(self.run_cli(full(), revision="XYZ").returncode, 2)
        self.assertEqual(self.run_cli(raw="not json").returncode, 2)
        self.assertEqual(self.run_cli(raw="[]").returncode, 2)


if __name__ == "__main__":
    unittest.main()
