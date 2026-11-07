import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import flaky_report as fr  # noqa: E402


class FlakyReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_file(self, name, body):
        path = self.tmp / name
        path.write_text(body if isinstance(body, str) else json.dumps({"results": body}), encoding="utf-8")
        return str(path)

    def cli(self, *paths):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "flaky_report.py"), *paths],
                              capture_output=True, text=True)

    def test_mixed_outcomes_are_flaky_and_never_a_pass(self):
        a = self.run_file("a.json", {"t1": "pass", "t2": "pass"})
        b = self.run_file("b.json", {"t1": "fail", "t2": "pass"})
        result = fr.classify([fr.load_run(Path(a)), fr.load_run(Path(b))])
        self.assertEqual(result["flaky"], ["t1"])
        self.assertEqual(result["quarantine_candidates"], ["t1"])
        self.assertEqual(result["stable_pass"], ["t2"])
        self.assertEqual(fr.exit_code(result), 1)
        self.assertEqual(self.cli(a, b).returncode, 1)

    def test_stable_fail_and_stable_pass(self):
        a = self.run_file("a.json", {"bad": "fail", "ok": "pass"})
        b = self.run_file("b.json", {"bad": "error", "ok": "pass"})
        result = fr.classify([fr.load_run(Path(a)), fr.load_run(Path(b))])
        self.assertEqual((result["stable_fail"], result["stable_pass"]), (["bad"], ["ok"]))
        self.assertEqual(fr.exit_code(result), 1)
        only_ok = self.run_file("c.json", {"ok": "pass"})
        self.assertEqual(self.cli(only_ok, only_ok).returncode, 0)

    def test_single_run_is_insufficient(self):
        a = self.run_file("a.json", {"t": "pass"})
        proc = self.cli(a)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("INSUFFICIENT t", proc.stdout)

    def test_missing_test_in_a_run_counts_as_error(self):
        a = self.run_file("a.json", {"t": "pass", "u": "pass"})
        b = self.run_file("b.json", {"u": "pass"})
        result = fr.classify([fr.load_run(Path(a)), fr.load_run(Path(b))])
        self.assertEqual(result["flaky"], ["t"])

    def test_skip_only_is_not_a_failure(self):
        a = self.run_file("a.json", {"t": "skip"})
        result = fr.classify([fr.load_run(Path(a)), fr.load_run(Path(a))])
        self.assertEqual(result["skipped"], ["t"])
        self.assertEqual(fr.exit_code(result), 0)

    def test_pass_plus_skips_is_insufficient_not_stable(self):
        a = self.run_file("a.json", {"t": "pass"})
        b = self.run_file("b.json", {"t": "skip"})
        result = fr.classify([fr.load_run(Path(a)), fr.load_run(Path(b))])
        self.assertEqual(result["insufficient"], ["t"])
        self.assertEqual(result["stable_pass"], [])
        self.assertEqual(fr.exit_code(result), 1)

    def test_malformed_input_exits_2_without_traceback(self):
        good = self.run_file("g.json", {"t": "pass"})
        bad_inputs = [
            self.run_file("b1.json", "{not json"),
            self.run_file("b2.json", '{"results": []}'),
            self.run_file("b3.json", '{"results": {"t": "maybe"}}'),
            self.run_file("b4.json", '{"results": {}}'),
            self.run_file("b5.json", '{"results": {"t": []}}'),
            self.run_file("b6.json", '{"results": {"t": {}}}'),
            str(self.tmp / "missing.json"),
        ]
        for bad in bad_inputs:
            proc = self.cli(good, bad)
            self.assertEqual(proc.returncode, 2, bad)
            self.assertNotIn("Traceback", proc.stderr)

    def test_output_is_deterministic_and_writes_nothing(self):
        a = self.run_file("a.json", {"z": "pass", "a": "fail"})
        b = self.run_file("b.json", {"z": "fail", "a": "fail"})
        before = sorted(p.name for p in self.tmp.iterdir())
        first, second = self.cli("--json", a, b), self.cli("--json", a, b)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
