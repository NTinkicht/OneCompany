import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
A, B = "a" * 64, "b" * 64


def manifest(mid="m1", **over):
    m = {"id": mid, "manifest_digest": A, "lockfile_digest": B, "lock_for_manifest_digest": A}
    m.update(over)
    return m


def update(uid="u1", **over):
    u = {"id": uid, "manifest": "m1", "source_digest_expected": A, "source_digest_actual": A,
         "stage": "staging", "canary": "pass", "promoted": True, "rolled_back": False,
         "rollback_proof": "verified", "authorized": False, "started_after_stop": False}
    u.update(over)
    return u


class DepsCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, updates, *extra, manifests=None, stop=False, raw=None, revision="1" * 40):
        path = self.tmp / "r.json"
        path.write_text(raw if raw is not None else json.dumps(
            {"revision": revision, "stop_active": stop,
             "manifests": [manifest()] if manifests is None else manifests, "updates": updates}), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "deps_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def assert_fails(self, updates, token, **kw):
        r = self.run_cli(updates, **kw)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(token, r.stdout)

    def test_clean_report_passes(self):
        r = self.run_cli([update(), update("u2", stage="production", authorized=True),
                          update("u3", canary="fail", promoted=False, rolled_back=True)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_json_output_is_deterministic(self):
        self.assertEqual(self.run_cli([update()], "--json").stdout, self.run_cli([update()], "--json").stdout)

    def test_stale_lockfile_fails(self):
        self.assert_fails([], "LOCKFILE_STALE m1", manifests=[manifest(lock_for_manifest_digest=B)])
        self.assert_fails([], "LOCKFILE_STALE m1", manifests=[manifest(lock_for_manifest_digest=None)])

    def test_missing_lockfile_fails(self):
        self.assert_fails([], "LOCKFILE_MISSING m1", manifests=[manifest(lockfile_digest=None)])

    def test_source_tamper_fails(self):
        self.assert_fails([update(source_digest_actual=B)], "SOURCE_TAMPER u1")

    def test_stop_ignored_only_when_stop_active(self):
        self.assert_fails([update(started_after_stop=True)], "STOP_IGNORED u1", stop=True)
        r = self.run_cli([update(started_after_stop=True)], stop=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_promotion_without_passing_canary_fails(self):
        for canary in ("fail", "not_run"):
            self.assert_fails([update(canary=canary)], "UNPROVEN_PROMOTION u1")

    def test_promotion_without_rollback_proof_fails(self):
        self.assert_fails([update(rollback_proof="missing")], "NO_ROLLBACK_PROOF u1")

    def test_failed_canary_must_be_recovered(self):
        self.assert_fails([update(canary="fail", promoted=False, rolled_back=False)], "UNRECOVERED_FAILURE u1")

    def test_production_needs_human_authorization(self):
        self.assert_fails([update(stage="production", authorized=False)], "PRODUCTION_UNAUTHORIZED u1")

    def test_unpromoted_production_candidate_needs_no_authorization(self):
        r = self.run_cli([update(stage="production", promoted=False, canary="not_run", authorized=False)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_malformed_input_is_unable_to_verify(self):
        cases = [
            self.run_cli([update()], raw="not json"),
            self.run_cli([update()], raw="[]"),
            self.run_cli([update()], revision="abc"),
            self.run_cli([update()], manifests=[]),
            self.run_cli([update()], manifests=[manifest(), manifest()]),
            self.run_cli([update()], manifests=[manifest(manifest_digest="zz")]),
            self.run_cli([update()], manifests=[manifest(lockfile_digest="zz")]),
            self.run_cli([update(manifest="nope")]),
            self.run_cli([update(), update()]),
            self.run_cli([update(source_digest_actual="zz")]),
            self.run_cli([update(promoted="yes")]),
            self.run_cli([update(canary="weird")]),
            self.run_cli([update(stage="prod")]),
            self.run_cli([update()], stop="no"),
            self.run_cli(["x"]),
        ]
        for r in cases:
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_cli_registered(self):
        r = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "deps-check", "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
