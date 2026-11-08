import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import regression_report as rr  # noqa: E402


class RegressionReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, name, body):
        path = self.tmp / name
        path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
        return path

    def regs(self, *items):
        return self.write("r.json", {"regressions": [
            {"id": i, "test": t, "failed_before_fix": f} for i, t, f in items]})

    def run_file(self, results):
        return self.write("run.json", {"results": results})

    def cli(self, *paths):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "regression_report.py"),
                               *map(str, paths)], capture_output=True, text=True)

    def test_each_state(self):
        regs = rr.load_regressions(self.regs(("R1", "t1", True), ("R2", "t2", False),
                                             ("R3", "t3", True), ("R4", "t4", True),
                                             ("R5", "t5", True)))
        run = rr.load_run(self.run_file({"t1": "pass", "t2": "pass", "t3": "fail", "t5": "skip"}))
        result = rr.classify(regs, run)
        self.assertEqual(result["proven"], ["R1"])
        self.assertEqual(result["unproven"], ["R2"])
        self.assertEqual(result["failing"], ["R3", "R5"])
        self.assertEqual(result["missing"], ["R4"])
        self.assertEqual(rr.exit_code(result), 1)

    def test_all_proven_exits_zero(self):
        proc = self.cli(self.regs(("R1", "t1", True)), self.run_file({"t1": "pass"}))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("1/1", proc.stdout)

    def test_unproven_exits_one(self):
        proc = self.cli(self.regs(("R1", "t1", False)), self.run_file({"t1": "pass"}))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("UNPROVEN R1", proc.stdout)

    def test_non_boolean_flag_rejected(self):
        bad = self.write("b.json", {"regressions": [{"id": "R1", "test": "t", "failed_before_fix": "true"}]})
        self.assertEqual(self.cli(bad, self.run_file({"t": "pass"})).returncode, 2)

    def test_duplicate_id_and_malformed_rejected(self):
        dup = self.regs(("R1", "a", True), ("R1", "b", True))
        self.assertEqual(self.cli(dup, self.run_file({"a": "pass"})).returncode, 2)
        self.assertEqual(self.cli(self.write("x.json", "{"), self.run_file({"a": "pass"})).returncode, 2)
        self.assertEqual(self.cli(self.write("n.json", {"other": []}), self.run_file({"a": "pass"})).returncode, 2)
        self.assertEqual(self.cli(self.write("n2.json", {"regressions": "x"}), self.run_file({"a": "pass"})).returncode, 2)
        self.assertEqual(self.cli(self.regs(("R1", "a", True)), self.tmp / "nope.json").returncode, 2)

    def test_empty_regressions_list_is_valid(self):
        proc = self.cli(self.write("e.json", {"regressions": []}), self.run_file({"a": "pass"}))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("0/0 regressions proven", proc.stdout)

    def test_json_output(self):
        proc = self.cli(self.regs(("R1", "t1", True)), self.run_file({"t1": "pass"}), "--json")
        self.assertEqual(json.loads(proc.stdout)["proven"], ["R1"])


if __name__ == "__main__":
    unittest.main()
