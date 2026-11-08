import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import mutation_check as mc  # noqa: E402


def mu(mid, status="killed", **over):
    item = {"id": mid, "file": "a.py", "status": status}
    item.update(over)
    return item


class MutationCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, mutants, revision="1" * 40):
        path = self.tmp / "r.json"
        path.write_text(mutants if isinstance(mutants, str) else json.dumps({"revision": revision, "mutants": mutants}), encoding="utf-8")
        return path

    def cli(self, path, *extra):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "mutation_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def run_cli(self, mutants, *extra):
        return self.cli(self.write(mutants), *extra)

    def test_all_killed_passes_and_timeout_counts(self):
        r = self.run_cli([mu("a"), mu("b", "timeout")])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("score 100%", r.stdout)

    def test_survived_fails_even_with_low_threshold(self):
        r = self.run_cli([mu("a"), mu("b", "survived")], "--min-score", "0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("SURVIVED b", r.stdout)

    def test_uncovered_fails(self):
        r = self.run_cli([mu("a"), mu("b", "no_coverage")], "--min-score", "0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("UNCOVERED b", r.stdout)

    def test_equivalent_needs_justification(self):
        for over in ({}, {"justification": "  "}):
            r = self.run_cli([mu("a"), mu("b", "equivalent", **over)])
            self.assertEqual(r.returncode, 1)
            self.assertIn("UNJUSTIFIED_EQUIVALENT b", r.stdout)
        r = self.run_cli([mu("a"), mu("b", "equivalent", justification="dead branch")])
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_score_floor_and_equivalent_excluded(self):
        result = mc.classify([mu("a"), mu("b"), mu("c", "survived"), mu("d", "equivalent", justification="x")])
        self.assertEqual(result["score"], 66)
        self.assertEqual(mc.exit_code({"score": 100, "survived": [], "uncovered": [], "unjustified_equivalent": []}, 100), 0)
        self.assertEqual(mc.exit_code({"score": 79, "survived": [], "uncovered": [], "unjustified_equivalent": []}, 80), 1)

    def test_all_equivalent_is_unable_to_verify(self):
        r = self.run_cli([mu("a", "equivalent", justification="x")])
        self.assertEqual(r.returncode, 2)
        self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_malformed_input_exits_2(self):
        bad = ["not json", "[]", json.dumps({"revision": "1" * 40, "mutants": []}),
               json.dumps({"revision": "abc", "mutants": [mu("a")]}),
               json.dumps({"revision": "1" * 40, "mutants": [mu("a", "bogus")]}),
               json.dumps({"revision": "1" * 40, "mutants": [mu("a"), mu("a")]}),
               json.dumps({"revision": "1" * 40, "mutants": [mu("a", file="")]}),
               json.dumps({"revision": "1" * 40 + "\n", "mutants": [mu("a")]})]
        for body in bad:
            r = self.run_cli(body)
            self.assertEqual(r.returncode, 2, body)
            self.assertIn("UNABLE TO VERIFY", r.stderr)
        self.assertEqual(self.cli(self.tmp / "missing.json").returncode, 2)
        for score in ("101", "-1"):
            self.assertEqual(self.run_cli([mu("a")], "--min-score", score).returncode, 2)

    def test_json_output(self):
        r = self.run_cli([mu("a"), mu("b", "survived")], "--json", "--min-score", "0")
        self.assertEqual(json.loads(r.stdout)["survived"], ["b"])


if __name__ == "__main__":
    unittest.main()
