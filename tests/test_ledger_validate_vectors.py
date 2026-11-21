"""OC-P0-04 vectors for ledger_validate: lease-lifecycle and enablement refusals.

Each test copies the real control-plane documents into a temporary directory,
applies one mutation and asserts the exact validator message.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger_validate  # noqa: E402

DOCUMENTS = ("ledger.json", "config.json", "supervision.json")


class LedgerValidateVectors(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.control = Path(tmp.name)
        for name in DOCUMENTS:
            shutil.copy(ROOT / ".onecompany" / name, self.control / name)
        patcher = mock.patch.object(ledger_validate, "CONTROL", self.control)
        patcher.start()
        self.addCleanup(patcher.stop)

    def edit(self, name, mutate):
        path = self.control / name
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def run_validator(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ledger_validate.main()
        return code, out.getvalue()

    def assert_refused(self, message):
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn(f"ERROR: {message}", output)
        self.assertIn("FAILED (1 error(s)", output)

    def test_repository_ledger_passes(self):
        code, output = self.run_validator()
        self.assertEqual(code, 0, output)
        self.assertIn("ledger validation PASS", output)

    def test_duplicate_event_types_refused(self):
        self.edit("ledger.json", lambda d: d["accepted_event_types"].append("GATE"))
        self.assert_refused("ledger.accepted_event_types must be unique")

    def test_missing_required_event_type_refused(self):
        self.edit("ledger.json", lambda d: d["accepted_event_types"].remove("ROLE_LEASE_REAPED"))
        self.assert_refused("ledger is missing required event types: ['ROLE_LEASE_REAPED']")

    def test_non_positive_or_non_integer_ttl_refused(self):
        for bad in (0, -5, "14400", True, None):
            with self.subTest(ttl=bad):
                self.edit("ledger.json", lambda d, bad=bad: d["lease_lifecycle"].__setitem__("ttl_seconds", bad))
                self.assert_refused("ledger.lease_lifecycle.ttl_seconds must be a positive integer")

    def test_renewal_progress_must_be_exactly_pr_head(self):
        for bad in ([], ["pr_head", "comment"], ["comment"]):
            with self.subTest(kinds=bad):
                self.edit("ledger.json", lambda d, bad=bad: d["lease_lifecycle"].__setitem__("renewal_progress_kinds", bad))
                self.assert_refused("ledger.lease_lifecycle.renewal_progress_kinds must be ['pr_head']")

    def test_expiry_must_revoke_authority(self):
        self.edit("ledger.json", lambda d: d["lease_lifecycle"].__setitem__("implicit_expiry_revokes_authority", False))
        self.assert_refused("ledger lease expiry must revoke implementation authority")

    def test_enabled_ledger_requires_positive_issue_number(self):
        for bad in (0, -1, "45", None):
            with self.subTest(issue=bad):
                self.edit("ledger.json", lambda d, bad=bad: d.__setitem__("issue_number", bad))
                self.assert_refused("enabled ledger requires a positive issue_number")

    def test_enabled_ledger_requires_trusted_publishers(self):
        self.edit("ledger.json", lambda d: d.__setitem__("trusted_publisher_logins", []))
        self.assert_refused("enabled ledger requires trusted_publisher_logins")

    def test_l4_continuous_autonomy_requires_enabled_ledger(self):
        self.edit("ledger.json", lambda d: d.__setitem__("enabled", False))
        self.edit("supervision.json", lambda d: d.__setitem__("mode", "observe"))
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn("ERROR: L3+ autonomous delivery requires the durable ledger enabled", output)
        self.assertIn("ERROR: L4/L5 continuous autonomy requires the durable ledger enabled", output)
        self.assertNotIn("orchestrating scheduled supervision", output)

    def test_disabled_ledger_allowed_below_l3_when_not_orchestrating(self):
        self.edit("ledger.json", lambda d: d.__setitem__("enabled", False))
        self.edit("supervision.json", lambda d: d.__setitem__("mode", "observe"))
        self.edit("config.json", lambda d: d["autonomy"].__setitem__("level", "L2"))
        code, output = self.run_validator()
        self.assertEqual(code, 0, output)

    def test_orchestrating_supervision_requires_enabled_ledger(self):
        self.edit("ledger.json", lambda d: d.__setitem__("enabled", False))
        self.edit("config.json", lambda d: d["autonomy"].__setitem__("level", "L2"))
        self.assert_refused("orchestrating scheduled supervision requires the durable ledger enabled")

    def test_unknown_autonomy_level_reported(self):
        self.edit("config.json", lambda d: d["autonomy"].__setitem__("level", "L99"))
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn("ERROR: ", output)

    def test_team_room_mismatch_warns_without_failing(self):
        self.edit("supervision.json", lambda d: d["coordination"].__setitem__("team_room_issue_number", 99999))
        code, output = self.run_validator()
        self.assertEqual(code, 0, output)
        self.assertIn("WARN: supervision Team Room issue differs from durable ledger issue", output)


if __name__ == "__main__":
    unittest.main()
