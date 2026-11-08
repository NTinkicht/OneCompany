import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def msg(mid, **over):
    m = {"id": mid, "actor": "codex", "seq": 1, "idempotency_key": "k-" + mid, "payload_digest": "a" * 64,
         "kind": "handoff", "authority": "message", "claims_approval": False, "signature": "valid",
         "attempt": 1, "effect": "applied"}
    m.update(over)
    return m


class CommsCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, messages, *extra, trusted=("codex", "claude"), max_attempts=3, raw=None, revision="1" * 40):
        path = self.tmp / "r.json"
        path.write_text(raw if raw is not None else json.dumps(
            {"revision": revision, "trusted_actors": list(trusted), "max_attempts": max_attempts,
             "messages": messages}), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "comms_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def assert_fails(self, messages, token, **kw):
        r = self.run_cli(messages, **kw)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(token, r.stdout)

    def test_clean_report_passes(self):
        good = [msg("m1"), msg("m2", seq=2), msg("m3", actor="claude", seq=1),
                msg("m4", kind="approval", authority="ledger", seq=3)]
        r = self.run_cli(good)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_json_output_is_deterministic(self):
        a = self.run_cli([msg("m1")], "--json").stdout
        b = self.run_cli([msg("m1")], "--json").stdout
        self.assertEqual(a, b)

    def test_ignored_duplicate_and_rejected_spoof_are_fine(self):
        r = self.run_cli([msg("m1"), msg("m2", idempotency_key="k-m1", effect="ignored"),
                          msg("m3", actor="mallory", signature="missing", effect="rejected")])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_spoofed_actor_applied_fails(self):
        self.assert_fails([msg("m1", actor="mallory")], "SPOOFED_ACTOR m1")

    def test_bad_signature_applied_fails(self):
        for sig in ("invalid", "missing"):
            self.assert_fails([msg("m1", signature=sig)], "SPOOFED_ACTOR m1")

    def test_duplicate_applied_fails(self):
        self.assert_fails([msg("m1"), msg("m2", seq=2, idempotency_key="k-m1")], "DUPLICATE_APPLIED m2")

    def test_key_reuse_with_different_payload_fails(self):
        self.assert_fails([msg("m1"), msg("m2", seq=2, idempotency_key="k-m1", payload_digest="b" * 64)],
                          "KEY_REUSE_CONFLICT m2")

    def test_out_of_order_fails(self):
        self.assert_fails([msg("m1", seq=5), msg("m2", seq=4)], "ORDER_VIOLATION m2")
        self.assert_fails([msg("m1", seq=5), msg("m2", seq=5)], "ORDER_VIOLATION m2")

    def test_unbounded_retry_fails(self):
        self.assert_fails([msg("m1", attempt=4)], "RETRY_UNBOUNDED m1")

    def test_handoff_as_approval_fails(self):
        for kind in ("handoff", "status"):
            self.assert_fails([msg("m1", kind=kind, claims_approval=True)], "HANDOFF_AS_APPROVAL m1")

    def test_approval_without_ledger_authority_fails(self):
        self.assert_fails([msg("m1", kind="approval", authority="message")], "UNTRUSTED_APPROVAL m1")

    def test_malformed_input_is_unable_to_verify(self):
        cases = [
            self.run_cli([msg("m1")], raw="not json"),
            self.run_cli([msg("m1")], raw="[]"),
            self.run_cli([msg("m1")], revision="abc"),
            self.run_cli([msg("m1")], trusted=()),
            self.run_cli([msg("m1")], max_attempts=0),
            self.run_cli([msg("m1")], max_attempts=True),
            self.run_cli([]),
            self.run_cli([msg("m1"), msg("m1")]),
            self.run_cli([msg("m1", payload_digest="zz")]),
            self.run_cli([msg("m1", effect="weird")]),
            self.run_cli([msg("m1", claims_approval="no")]),
            self.run_cli([msg("m1", seq=-1)]),
            self.run_cli(["x"]),
        ]
        for r in cases:
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_cli_registered(self):
        r = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "comms-check", "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
