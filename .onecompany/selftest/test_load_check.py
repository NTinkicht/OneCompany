import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import load_check as lc  # noqa: E402


def sc(sid, **over):
    item = {"id": sid, "requests": 1000, "errors": 0, "duration_ms": 10000, "p95_ms": 200}
    item.update(over)
    return item


class LoadCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, scenarios, *extra, revision="1" * 40):
        path = self.tmp / "r.json"
        path.write_text(scenarios if isinstance(scenarios, str) else json.dumps({"revision": revision, "scenarios": scenarios}), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "load_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def test_within_budgets_passes(self):
        r = self.run_cli([sc("a"), sc("b")])
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_any_error_breaches_default_zero_budget(self):
        r = self.run_cli([sc("a", errors=1)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("BREACH a error_budget", r.stdout)

    def test_error_budget_boundary_is_integer_exact(self):
        self.assertEqual(self.run_cli([sc("a", errors=10)], "--max-error-permille", "10").returncode, 0)
        self.assertEqual(self.run_cli([sc("a", errors=11)], "--max-error-permille", "10").returncode, 1)

    def test_latency_boundary(self):
        self.assertEqual(self.run_cli([sc("a", p95_ms=1000)]).returncode, 0)
        r = self.run_cli([sc("a", p95_ms=1001)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("latency", r.stdout)

    def test_throughput_boundary(self):
        self.assertEqual(self.run_cli([sc("a")], "--min-rps", "100").returncode, 0)
        r = self.run_cli([sc("a")], "--min-rps", "101")
        self.assertEqual(r.returncode, 1)
        self.assertIn("throughput", r.stdout)

    def test_multiple_breaches_sorted_json(self):
        r = self.run_cli([sc("z", p95_ms=5000), sc("a", errors=5, p95_ms=5000)], "--json")
        self.assertEqual(r.returncode, 1)
        out = json.loads(r.stdout)
        self.assertEqual(list(out["breaches"]), ["a", "z"])
        self.assertEqual(out["breaches"]["a"], ["error_budget", "latency"])

    def test_one_bad_scenario_among_good_fails(self):
        self.assertEqual(self.run_cli([sc("a"), sc("b", errors=1)]).returncode, 1)

    def test_malformed_inputs_exit_2(self):
        bad = [
            "not json", "[]", json.dumps({"revision": "1" * 40}),
            [], [sc("a"), sc("a")], [sc("a", requests=0)], [sc("a", duration_ms=0)],
            [sc("a", errors=1001)], [sc("a", errors=-1)], [sc("a", p95_ms=-1)],
            [sc("a", requests=True)], [sc("a", p95_ms=1.5)], [sc("a", p95_ms="9")],
            [sc("")], ["x"],
        ]
        for case in bad:
            r = self.run_cli(case)
            self.assertEqual(r.returncode, 2, case)
            self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_bad_revision_and_budgets_exit_2(self):
        self.assertEqual(self.run_cli([sc("a")], revision="abc").returncode, 2)
        self.assertEqual(self.run_cli([sc("a")], revision="1" * 40 + "\n").returncode, 2)
        for flag in ("--max-error-permille", "--max-p95-ms", "--min-rps"):
            self.assertEqual(self.run_cli([sc("a")], flag, "-1").returncode, 2)

    def test_missing_file_exits_2(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "load_check.py"), str(self.tmp / "nope.json")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_registered_in_onecompany(self):
        self.assertIn('"load-check"', (ROOT / "onecompany.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
