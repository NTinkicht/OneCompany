import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def viol(rule, impact="serious", nodes=1):
    return {"rule": rule, "impact": impact, "nodes": nodes}


def page(pid, violations=(), waived=()):
    return {"id": pid, "violations": list(violations), "waived": list(waived)}


class A11yCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, pages, *extra, revision="1" * 40):
        path = self.tmp / "r.json"
        path.write_text(pages if isinstance(pages, str) else json.dumps({"revision": revision, "pages": pages}), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "a11y_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def test_clean_pages_pass(self):
        self.assertEqual(self.run_cli([page("a"), page("b")]).returncode, 0)

    def test_serious_and_critical_block(self):
        for impact in ("serious", "critical"):
            r = self.run_cli([page("a", [viol("color-contrast", impact)])])
            self.assertEqual(r.returncode, 1, impact)
            self.assertIn("BLOCKING a color-contrast", r.stdout)

    def test_minor_and_moderate_only_warn(self):
        r = self.run_cli([page("a", [viol("x", "minor"), viol("y", "moderate")])])
        self.assertEqual(r.returncode, 0)
        self.assertIn("WARN a x", r.stdout)

    def test_waiver_suppresses_matching_blocking_violation(self):
        r = self.run_cli([page("a", [viol("label")], ["label"])])
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_waiver_is_per_page(self):
        r = self.run_cli([page("a", [viol("label")], ["label"]), page("b", [viol("label")])])
        self.assertEqual(r.returncode, 1)
        self.assertIn("BLOCKING b label", r.stdout)
        self.assertNotIn("BLOCKING a", r.stdout)

    def test_stale_waiver_fails(self):
        r = self.run_cli([page("a", [], ["label"])])
        self.assertEqual(r.returncode, 1)
        self.assertIn("STALE_WAIVER a label", r.stdout)

    def test_waiver_for_only_a_warning_violation_is_stale_free(self):
        self.assertEqual(self.run_cli([page("a", [viol("x", "minor")], ["x"])]).returncode, 0)

    def test_json_output_is_deterministic_and_sorted(self):
        pages = [page("b", [viol("z"), viol("a")]), page("a", [viol("q")])]
        r1 = self.run_cli(pages, "--json")
        r2 = self.run_cli(list(reversed(pages)), "--json")
        self.assertEqual(r1.stdout, r2.stdout)
        self.assertEqual(json.loads(r1.stdout)["blocking"], ["a q", "b a", "b z"])

    def test_malformed_inputs_are_unable_to_verify(self):
        bad = [
            "not json", "[]", json.dumps({"revision": "1" * 40, "pages": []}),
            [page("a"), page("a")],
            [page("", [])],
            [page("a", [viol("r", "severe")])],
            [page("a", [viol("r", [])])],
            [page("a", [viol("r", {})])],
            [page("a", [viol("r", nodes=0)])],
            [page("a", [viol("r", nodes=True)])],
            [page("a", [viol("r", nodes=1.5)])],
            [page("a", [{"rule": 3, "impact": "minor", "nodes": 1}])],
            [page("a", [], [""])],
            [{"id": "a", "violations": "x"}],
        ]
        for case in bad:
            r = self.run_cli(case)
            self.assertEqual(r.returncode, 2, case)
            self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_bad_revision_and_missing_file(self):
        self.assertEqual(self.run_cli([page("a")], revision="xyz").returncode, 2)
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "a11y_check.py"), str(self.tmp / "none.json")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_registered_in_entry_point(self):
        r = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "a11y-check", "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
