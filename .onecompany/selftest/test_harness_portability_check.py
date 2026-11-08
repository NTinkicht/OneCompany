import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = "a" * 64
RES = "b" * 64


def backend(bid, **over):
    b = {"id": bid, "fixture_digest": FIX, "result_digest": RES, "status": "pass",
         "sandbox_escape_attempt": "refused", "stale_context_attempt": "rejected", "crash_recovery": "recovered"}
    b.update(over)
    return b


def good():
    return [backend("claude"), backend("codex")]


class HarnessPortabilityCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, backends, *extra, required=("claude", "codex"), revision="1" * 40, raw=None):
        path = self.tmp / "r.json"
        path.write_text(raw if raw is not None else json.dumps(
            {"revision": revision, "required_backends": list(required), "backends": backends}), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "harness_portability_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def assert_fails(self, backends, token, **kw):
        r = self.run_cli(backends, **kw)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(token, r.stdout)

    def test_portable_report_passes(self):
        r = self.run_cli(good())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_json_output_is_deterministic(self):
        a = self.run_cli(good(), "--json").stdout
        b = self.run_cli(list(reversed(good())), "--json").stdout
        self.assertEqual(a, b)

    def test_missing_required_backend_fails(self):
        self.assert_fails([backend("claude")], "MISSING_BACKEND codex")

    def test_non_pass_status_fails(self):
        for st in ("fail", "error", "skipped"):
            self.assert_fails([backend("claude"), backend("codex", status=st)], "NOT_PASSING codex")

    def test_fixture_mismatch_fails(self):
        self.assert_fails([backend("claude"), backend("codex", fixture_digest="c" * 64)], "FIXTURE_MISMATCH")

    def test_result_divergence_fails(self):
        self.assert_fails([backend("claude"), backend("codex", result_digest="c" * 64)], "RESULT_DIVERGENCE")

    def test_sandbox_escape_not_refused_fails(self):
        for v in ("allowed", "not_run"):
            self.assert_fails([backend("claude"), backend("codex", sandbox_escape_attempt=v)], "SANDBOX_ESCAPE_NOT_REFUSED codex")

    def test_stale_context_not_rejected_fails(self):
        for v in ("accepted", "not_run"):
            self.assert_fails([backend("claude"), backend("codex", stale_context_attempt=v)], "STALE_CONTEXT_NOT_REJECTED codex")

    def test_crash_not_recovered_fails(self):
        for v in ("lost", "not_run"):
            self.assert_fails([backend("claude"), backend("codex", crash_recovery=v)], "CRASH_NOT_RECOVERED codex")

    def test_malformed_input_is_unable_to_verify(self):
        cases = [
            self.run_cli(good(), raw="not json"),
            self.run_cli(good(), raw="[]"),
            self.run_cli(good(), revision="abc"),
            self.run_cli(good(), required=()),
            self.run_cli(good(), required=("claude", "claude")),
            self.run_cli([]),
            self.run_cli([backend("claude"), backend("claude")]),
            self.run_cli([backend("claude", fixture_digest="zz"), backend("codex")]),
            self.run_cli([backend("claude", status="weird"), backend("codex")]),
            self.run_cli([backend("claude", crash_recovery=None), backend("codex")]),
            self.run_cli(["x"]),
        ]
        for r in cases:
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_missing_report_file_is_unable_to_verify(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "harness_portability_check.py"), str(self.tmp / "nope.json")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_wired_into_cli(self):
        path = self.tmp / "r.json"
        path.write_text(json.dumps({"revision": "1" * 40, "required_backends": ["claude"], "backends": [backend("claude")]}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "harness-check", str(path)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
