import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import quarantine_check as qc  # noqa: E402
from flaky_report import load_run  # noqa: E402


def entry(test, issue="#1", reason="flaky"):
    return {"test": test, "issue": issue, "reason": reason}


class QuarantineCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, name, body):
        path = self.tmp / name
        path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
        return path

    def cli(self, q, r):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "quarantine_check.py"), str(q), str(r)],
                              capture_output=True, text=True)

    def test_unregistered_skip_is_a_bypass(self):
        q = self.write("q.json", {"quarantined": []})
        r = self.write("r.json", {"results": {"a": "pass", "b": "skip"}})
        result = qc.classify(qc.load_quarantine(q), load_run(r))
        self.assertEqual(result["unregistered_skip"], ["b"])
        self.assertEqual(qc.exit_code(result), 1)
        self.assertEqual(self.cli(q, r).returncode, 1)

    def test_registered_failing_or_skipped_test_is_quarantined_and_clean(self):
        q = self.write("q.json", {"quarantined": [entry("a"), entry("b")]})
        r = self.write("r.json", {"results": {"a": "fail", "b": "skip", "c": "pass"}})
        result = qc.classify(qc.load_quarantine(q), load_run(r))
        self.assertEqual(result["quarantined"], ["a", "b"])
        self.assertEqual(qc.exit_code(result), 0)
        self.assertEqual(self.cli(q, r).returncode, 0)

    def test_passing_registered_test_is_stale(self):
        q = self.write("q.json", {"quarantined": [entry("a")]})
        r = self.write("r.json", {"results": {"a": "pass"}})
        result = qc.classify(qc.load_quarantine(q), load_run(r))
        self.assertEqual(result["stale_entry"], ["a"])
        self.assertEqual(result["quarantined"], [])
        self.assertEqual(self.cli(q, r).returncode, 1)

    def test_registered_test_absent_from_run_is_missing(self):
        q = self.write("q.json", {"quarantined": [entry("gone")]})
        r = self.write("r.json", {"results": {"a": "pass"}})
        result = qc.classify(qc.load_quarantine(q), load_run(r))
        self.assertEqual(result["missing"], ["gone"])
        self.assertEqual(self.cli(q, r).returncode, 1)

    def test_malformed_input_exits_two(self):
        r = self.write("r.json", {"results": {"a": "pass"}})
        bad = [
            "not json",
            {"quarantined": "x"},
            {"quarantined": ["a"]},
            {"quarantined": [entry("a", issue="")]},
            {"quarantined": [entry("a", reason="  ")]},
            {"quarantined": [{"test": "a", "issue": "#1"}]},
            {"quarantined": [entry("a"), entry("a")]},
        ]
        for i, body in enumerate(bad):
            q = self.write(f"q{i}.json", body)
            proc = self.cli(q, r)
            self.assertEqual(proc.returncode, 2, body)
            self.assertIn("UNABLE TO VERIFY", proc.stderr)
        self.assertEqual(self.cli(self.tmp / "nope.json", r).returncode, 2)
        self.assertEqual(self.cli(self.write("q.json", {"quarantined": []}), self.write("r2.json", "{}")).returncode, 2)

    def test_json_output_is_deterministic(self):
        q = self.write("q.json", {"quarantined": [entry("z"), entry("a")]})
        r = self.write("r.json", {"results": {"z": "error", "a": "fail", "s2": "skip", "s1": "skip"}})
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "quarantine_check.py"), str(q), str(r), "--json"],
                              capture_output=True, text=True)
        data = json.loads(proc.stdout)
        self.assertEqual(data["quarantined"], ["a", "z"])
        self.assertEqual(data["unregistered_skip"], ["s1", "s2"])
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
