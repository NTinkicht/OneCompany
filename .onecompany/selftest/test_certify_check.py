import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import certify_check  # noqa: E402

REV = "1" * 40


def manifest():
    return {"revision": REV, "certifier": "reviewer-a", "authors": ["writer-b"],
            "scenarios": [{"id": s, "result": "pass", "evidence_sha256": "a" * 64, "revision": REV,
                           "error_rate": 0.0, "p95_ms": 100, "ac_ids": ["AC-1"]}
                          for s in certify_check.SCENARIOS]}


class CertifyCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, data=None, raw=None):
        p = self.tmp / "m.json"
        p.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "certify_check.py"), str(p)],
                              capture_output=True, text=True)

    def assert_nogo(self, data, line):
        r = self.run_cli(data)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("NO-GO", r.stdout)
        self.assertIn(line, r.stdout)

    def test_complete_manifest_is_go(self):
        r = self.run_cli(manifest())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("GO (7 scenarios)", r.stdout)

    def test_missing_scenario(self):
        m = manifest(); m["scenarios"].pop()
        self.assert_nogo(m, "MISSING failure-stale-head")

    def test_unexpected_scenario(self):
        m = manifest(); m["scenarios"].append(dict(m["scenarios"][0], id="extra"))
        self.assert_nogo(m, "UNEXPECTED extra")

    def test_failed_scenario(self):
        m = manifest(); m["scenarios"][0]["result"] = "fail"
        self.assert_nogo(m, "FAILED create-fresh")

    def test_bad_evidence_digest(self):
        for bad in ("short", "A" * 64, ""):
            m = manifest(); m["scenarios"][1]["evidence_sha256"] = bad
            self.assert_nogo(m, "EVIDENCE adopt-existing")

    def test_stale_revision(self):
        m = manifest(); m["scenarios"][2]["revision"] = "2" * 40
        self.assert_nogo(m, "STALE_REVISION portfolio-two-app")

    def test_error_budget(self):
        m = manifest(); m["scenarios"][3]["error_rate"] = 0.011
        self.assert_nogo(m, "ERROR_BUDGET failure-ci-red")
        m["scenarios"][3]["error_rate"] = 0.01
        self.assertEqual(self.run_cli(m).returncode, 0)

    def test_latency_budget(self):
        m = manifest(); m["scenarios"][4]["p95_ms"] = 2001
        self.assert_nogo(m, "LATENCY_BUDGET failure-reviewer-outage")
        m["scenarios"][4]["p95_ms"] = 2000
        self.assertEqual(self.run_cli(m).returncode, 0)

    def test_untraced(self):
        m = manifest(); m["scenarios"][5]["ac_ids"] = []
        self.assert_nogo(m, "UNTRACED failure-budget-exhausted")

    def test_certifier_must_not_be_author(self):
        m = manifest(); m["authors"].append(" Reviewer-A ")
        self.assert_nogo(m, "INDEPENDENCE reviewer-a")

    def test_malformed_input_is_unable_to_verify(self):
        cases = []
        for mutate in (
            lambda m: m.update(revision="short"),
            lambda m: m.update(certifier=""),
            lambda m: m.update(authors="x"),
            lambda m: m.update(scenarios=[]),
            lambda m: m["scenarios"][0].update(error_rate=True),
            lambda m: m["scenarios"][0].update(p95_ms=-1),
            lambda m: m["scenarios"][0].update(result="maybe"),
            lambda m: m["scenarios"][0].update(ac_ids="AC-1"),
            lambda m: m["scenarios"][0].update(ac_ids=[""]),
            lambda m: m["scenarios"][0].update(ac_ids=["   "]),
            lambda m: m["scenarios"][0].update(p95_ms=float("nan")),
            lambda m: m["scenarios"][0].update(p95_ms=float("inf")),
            lambda m: m["scenarios"][0].update(error_rate=float("nan")),
            lambda m: m["scenarios"].append(dict(m["scenarios"][0])),
        ):
            m = manifest(); mutate(m); cases.append(m)
        for m in cases:
            r = self.run_cli(m)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("UNABLE TO VERIFY", r.stderr)
        self.assertEqual(self.run_cli(raw="not json").returncode, 2)
        self.assertEqual(self.run_cli(raw="[]").returncode, 2)

    def test_onecompany_registry_routes_to_script(self):
        r = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "certify-check", "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("certification", r.stdout)


if __name__ == "__main__":
    unittest.main()
