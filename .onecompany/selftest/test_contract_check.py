import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALL = ["contract", "property", "api", "db"]


def suite(sid, kind, statuses=("pass",), **extra):
    s = {"id": sid, "kind": kind, "tests": [{"id": f"t{i}", "status": st} for i, st in enumerate(statuses)]}
    if kind == "property":
        s.update({"seed": 7, "examples": 100})
    s.update(extra)
    return s


def good():
    return [suite(k, k) for k in ALL]


class ContractCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, suites, *extra, required=ALL, revision="1" * 40, raw=None):
        path = self.tmp / "r.json"
        path.write_text(raw if raw is not None else json.dumps(
            {"revision": revision, "required_kinds": required, "suites": suites}), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "contract_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def test_complete_passing_report_passes(self):
        self.assertEqual(self.run_cli(good()).returncode, 0)

    def test_missing_required_kind_fails(self):
        r = self.run_cli([s for s in good() if s["kind"] != "db"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISSING_KIND db", r.stdout)

    def test_unrequired_kind_may_be_absent(self):
        self.assertEqual(self.run_cli([suite("c", "contract")], required=["contract"]).returncode, 0)

    def test_empty_suite_fails(self):
        r = self.run_cli(good() + [suite("e", "api", ())])
        self.assertEqual(r.returncode, 1)
        self.assertIn("EMPTY_SUITE e", r.stdout)

    def test_failed_and_errored_tests_fail(self):
        r = self.run_cli([suite("c", "contract", ("pass", "fail", "error"))] + good()[1:])
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED c t1", r.stdout)
        self.assertIn("FAILED c t2", r.stdout)

    def test_skipped_test_fails_no_bypass(self):
        r = self.run_cli([suite("c", "contract", ("skipped",))] + good()[1:])
        self.assertEqual(r.returncode, 1)
        self.assertIn("SKIPPED c t0", r.stdout)

    def test_property_suite_needs_seed_and_examples(self):
        for extra in ({"seed": None}, {"examples": 0}):
            s = suite("p", "property")
            if "seed" in extra:
                del s["seed"]
            else:
                s.update(extra)
            r = self.run_cli([s] + [x for x in good() if x["kind"] != "property"])
            self.assertEqual(r.returncode, 1, extra)
            self.assertIn("UNREPRODUCIBLE p", r.stdout)

    def test_non_property_suite_needs_no_seed(self):
        self.assertEqual(self.run_cli(good()).returncode, 0)

    def test_output_sorted_and_deterministic(self):
        a = self.run_cli([suite("z", "api", ("fail",)), suite("a", "api", ("fail",))] + [x for x in good() if x["kind"] != "api"], "--json")
        self.assertEqual(json.loads(a.stdout)["problems"], ["FAILED a t0", "FAILED z t0"])
        b = self.run_cli([suite("a", "api", ("fail",)), suite("z", "api", ("fail",))] + [x for x in good() if x["kind"] != "api"], "--json")
        self.assertEqual(a.stdout, b.stdout)

    def test_malformed_inputs_exit_2(self):
        def rep(**kw):
            base = {"revision": "1" * 40, "required_kinds": ALL, "suites": good()}
            base.update(kw)
            return json.dumps(base)
        dup_test = suite("c", "contract")
        dup_test["tests"].append(dict(dup_test["tests"][0]))
        bad = [
            "not json", "[]", rep(revision="zz"), rep(required_kinds=[]), rep(required_kinds=["nope"]),
            rep(required_kinds=["api", "api"]), rep(suites=[]), rep(suites=[suite("a", "api"), suite("a", "db")]),
            rep(suites=[dup_test]), rep(suites=[suite("a", "weird")]), rep(suites=[suite("a", "api", ("maybe",))]),
            rep(suites=[suite("", "api")]), rep(suites=[suite("a", "property", seed=True)]),
            rep(suites=[suite("a", "property", examples="9")]),
            rep(suites=[{"id": "a", "kind": "api", "tests": "x"}]),
        ]
        for text in bad:
            r = self.run_cli(None, raw=text)
            self.assertEqual(r.returncode, 2, text)
            self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_missing_file_exits_2(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "contract_check.py"), str(self.tmp / "none.json")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_registered_in_cli(self):
        self.assertIn('"contract-check"', (ROOT / "onecompany.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
