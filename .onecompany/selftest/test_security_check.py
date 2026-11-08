import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fnd(fid, severity="high", kind="sast"):
    return {"id": fid, "severity": severity, "kind": kind}


def tgt(tid, findings=(), waived=()):
    return {"id": tid, "findings": list(findings), "waived": list(waived)}


class SecurityCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, targets, *extra, revision="1" * 40):
        path = self.tmp / "r.json"
        path.write_text(targets if isinstance(targets, str) else json.dumps({"revision": revision, "targets": targets}), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "security_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def test_clean_targets_pass(self):
        self.assertEqual(self.run_cli([tgt("a"), tgt("b")]).returncode, 0)

    def test_uppercase_hex_revision_accepted(self):
        self.assertEqual(self.run_cli([tgt("a")], revision="A" * 40).returncode, 0)
        self.assertEqual(self.run_cli([tgt("a")], revision="aB" * 20).returncode, 0)

    def test_high_and_critical_block(self):
        for sev in ("high", "critical"):
            r = self.run_cli([tgt("a", [fnd("X1", sev)])])
            self.assertEqual(r.returncode, 1, sev)
            self.assertIn("BLOCKING a X1", r.stdout)

    def test_low_and_medium_only_warn(self):
        r = self.run_cli([tgt("a", [fnd("x", "low"), fnd("y", "medium")])])
        self.assertEqual(r.returncode, 0)
        self.assertIn("WARN a x", r.stdout)

    def test_waiver_suppresses_matching_blocking_finding(self):
        self.assertEqual(self.run_cli([tgt("a", [fnd("X1")], ["X1"])]).returncode, 0)

    def test_waiver_is_per_target(self):
        r = self.run_cli([tgt("a", [fnd("X1")], ["X1"]), tgt("b", [fnd("X1")])])
        self.assertEqual(r.returncode, 1)
        self.assertIn("BLOCKING b X1", r.stdout)
        self.assertNotIn("BLOCKING a", r.stdout)

    def test_secret_blocks_at_any_severity(self):
        r = self.run_cli([tgt("a", [fnd("S1", "low", "secret")])])
        self.assertEqual(r.returncode, 1)
        self.assertIn("BLOCKING a S1", r.stdout)

    def test_secret_cannot_be_waived(self):
        r = self.run_cli([tgt("a", [fnd("S1", "critical", "secret")], ["S1"])])
        self.assertEqual(r.returncode, 1)
        self.assertIn("UNWAIVABLE a S1", r.stdout)
        self.assertIn("BLOCKING a S1", r.stdout)

    def test_stale_waiver_fails(self):
        r = self.run_cli([tgt("a", [], ["X1"])])
        self.assertEqual(r.returncode, 1)
        self.assertIn("STALE_WAIVER a X1", r.stdout)

    def test_waiving_low_finding_is_not_stale(self):
        self.assertEqual(self.run_cli([tgt("a", [fnd("x", "low")], ["x"])]).returncode, 0)

    def test_output_deterministic_and_sorted(self):
        r = self.run_cli([tgt("b", [fnd("Z")]), tgt("a", [fnd("Y"), fnd("X")])], "--json")
        self.assertEqual(json.loads(r.stdout)["blocking"], ["a X", "a Y", "b Z"])
        self.assertEqual(r.stdout, self.run_cli([tgt("a", [fnd("X"), fnd("Y")]), tgt("b", [fnd("Z")])], "--json").stdout)

    def test_malformed_inputs_exit_2(self):
        bad = [
            "not json", "[]", json.dumps({"revision": "1" * 40}),
            json.dumps({"revision": "zz", "targets": [tgt("a")]}),
            json.dumps({"revision": "1" * 40, "targets": []}),
            json.dumps({"revision": "1" * 40, "targets": [tgt("a"), tgt("a")]}),
            json.dumps({"revision": "1" * 40, "targets": [tgt("a", [fnd("x"), fnd("x")])]}),
            json.dumps({"revision": "1" * 40, "targets": [tgt("a", [fnd("x", "severe")])]}),
            json.dumps({"revision": "1" * 40, "targets": [tgt("a", [fnd("x", "high", "other")])]}),
            json.dumps({"revision": "1" * 40, "targets": [tgt("a", [fnd("x", ["high"])])]}),
            json.dumps({"revision": "1" * 40, "targets": [tgt("a", [fnd("")])]}),
            json.dumps({"revision": "1" * 40, "targets": [tgt("a", [], [3])]}),
            json.dumps({"revision": "1" * 40, "targets": [tgt("")]}),
        ]
        for text in bad:
            r = self.run_cli(text)
            self.assertEqual(r.returncode, 2, text)
            self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_missing_file_exits_2(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "security_check.py"), str(self.tmp / "none.json")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_registered_in_cli(self):
        self.assertIn('"security-check"', (ROOT / "onecompany.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
