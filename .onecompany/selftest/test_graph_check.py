import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def node(i, kind, sat=None, deps=(), effort=1):
    return {"id": i, "kind": kind, "satisfies": sat, "depends_on": list(deps), "effort": effort}


def nodes():
    return [node("o", "objective", effort=0), node("f", "feature", "o"), node("r", "requirement", "f"),
            node("a", "ac", "r"), node("w1", "wu", "a", effort=2), node("w2", "wu", "a", ["w1"], 3),
            node("w3", "wu", "a", ["w1"], 1)]


def base(**over):
    r = {"revision": "1" * 40, "change_base": "1" * 40, "nodes": nodes()}
    r.update(over)
    return r


class GraphCheckTests(unittest.TestCase):
    hung = False

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, report, *extra, raw=None):
        path = self.tmp / "r.json"
        path.write_text(raw if raw is not None else json.dumps(report), encoding="utf-8")
        # A hung checker (e.g. a mutated loop) must fail fast and leave no orphan child process.
        if GraphCheckTests.hung:
            self.fail("graph_check.py previously timed out")
        try:
            return subprocess.run([sys.executable, str(ROOT / "scripts" / "graph_check.py"), str(path), *extra],
                                  capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            GraphCheckTests.hung = True
            raise

    def assert_fails(self, report, token):
        r = self.run_cli(report)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(token, r.stdout)

    def assert_unverifiable(self, report=None, raw=None):
        r = self.run_cli(report, raw=raw)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_duplicate_keys_are_refused_not_last_wins(self):
        good = json.dumps(base())
        self.assertEqual(self.run_cli(None, raw=good).returncode, 0)  # positive control
        node_dup = good.replace('"id": "w2", "kind": "wu"', '"id": "w2", "depends_on": ["w1"], "kind": "wu"', 1)
        self.assertNotEqual(node_dup, good)
        top_dup = good.replace('{"revision"', '{"change_base": "' + "2" * 40 + '", "revision"', 1)
        self.assertNotEqual(top_dup, good)
        for raw in (node_dup, top_dup):
            r = self.run_cli(None, raw=raw)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("UNABLE TO VERIFY", r.stderr)
            self.assertIn("unreadable", r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_clean_graph_passes_with_critical_path(self):
        r = self.run_cli(base(), "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["critical_path"], ["w1", "w2"])

    def test_json_output_is_deterministic(self):
        self.assertEqual(self.run_cli(base(), "--json").stdout, self.run_cli(base(), "--json").stdout)

    def test_cycle_fails(self):
        n = nodes()
        n[4]["depends_on"] = ["w2"]
        self.assert_fails(base(nodes=n), "CYCLE among w1,w2")

    def test_dependents_of_a_cycle_are_not_cycle_members(self):
        n = nodes() + [node("w4", "wu", "a", ["w1"])]
        n[4]["depends_on"] = ["w2"]
        n[5]["depends_on"] = ["w1"]
        r = self.run_cli(base(nodes=n))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("CYCLE among w1,w2\n", r.stdout)
        self.assertIn("BLOCKED_BY_CYCLE w3,w4", r.stdout)

    def test_long_chain_with_dependent_first_ids_does_not_overflow(self):
        n = nodes()[:4] + [node(f"z{600 - k:03d}", "wu", "a", [f"z{600 - k + 1:03d}"] if k else [])
                           for k in range(600)]
        r = self.run_cli(base(nodes=n), "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(json.loads(r.stdout)["critical_path"]), 600)

    def test_stale_change_fails(self):
        self.assert_fails(base(change_base="2" * 40), "STALE_CHANGE")

    def test_level_skip_fails(self):
        n = nodes()
        n[4]["satisfies"] = "r"
        self.assert_fails(base(nodes=n), "LEVEL_SKIP w1")

    def test_uncovered_requirement_and_ac_fail(self):
        self.assert_fails(base(nodes=nodes()[:3]), "UNCOVERED r (requirement) has no ac")
        self.assert_fails(base(nodes=nodes()[:4]), "UNCOVERED a (ac) has no wu")

    def test_tie_breaks_by_id(self):
        n = nodes()
        n[5]["effort"] = n[6]["effort"] = 1
        r = self.run_cli(base(nodes=n), "--json")
        self.assertEqual(json.loads(r.stdout)["critical_path"], ["w1", "w2"])

    def test_priority_inversion_fails_with_positive_controls(self):
        def prio(w1, w2):
            n = nodes()
            n[4]["priority"], n[5]["priority"] = w1, w2
            return base(nodes=n)

        self.assert_fails(prio("P2", "P0"), "PRIORITY_INVERSION w2 (P0) depends on w1 (P2)")
        for ok in (("P0", "P2"), ("P1", "P1"), (None, "P0"), ("P3", None)):
            r = self.run_cli(prio(*ok))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_every_priority_inversion_is_reported(self):
        n = nodes()
        n[4]["priority"], n[5]["priority"], n[6]["priority"] = "P3", "P0", "P1"
        r = self.run_cli(base(nodes=n))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("PRIORITY_INVERSION w2 (P0) depends on w1 (P3)", r.stdout)
        self.assertIn("PRIORITY_INVERSION w3 (P1) depends on w1 (P3)", r.stdout)

    def test_invalid_priority_is_unverifiable(self):
        for bad_value in ("P9", 0, ["P0"], True):
            bad = nodes()
            bad[4]["priority"] = bad_value
            self.assert_unverifiable(base(nodes=bad))

    def test_malformed_inputs_are_unverifiable(self):
        self.assert_unverifiable(raw="{not json")
        self.assert_unverifiable(base(revision="x"))
        self.assert_unverifiable(base(nodes=[]))
        bad = nodes()
        bad[4]["depends_on"] = ["ghost"]
        self.assert_unverifiable(base(nodes=bad))
        bad = nodes()
        bad[4]["effort"] = True
        self.assert_unverifiable(base(nodes=bad))
        bad = nodes()
        bad[4]["kind"] = ["wu"]
        self.assert_unverifiable(base(nodes=bad))
        bad = nodes()
        bad[4]["depends_on"] = [["w2"]]
        self.assert_unverifiable(base(nodes=bad))
        bad = nodes() + [node("w1", "wu", "a")]
        self.assert_unverifiable(base(nodes=bad))


if __name__ == "__main__":
    unittest.main()
