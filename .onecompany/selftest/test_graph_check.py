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
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, report, *extra, raw=None):
        path = self.tmp / "r.json"
        path.write_text(raw if raw is not None else json.dumps(report), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "graph_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def assert_fails(self, report, token):
        r = self.run_cli(report)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(token, r.stdout)

    def assert_unverifiable(self, report=None, raw=None):
        r = self.run_cli(report, raw=raw)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("UNABLE TO VERIFY", r.stderr)

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
