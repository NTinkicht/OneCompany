from __future__ import annotations

import argparse
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lease  # noqa: E402


class LeaseCommandFailClosedTests(unittest.TestCase):
    """Public lease commands must translate coordination outages into refusal."""

    def _capture(self, func, args):
        output = io.StringIO()
        with redirect_stdout(output):
            result = func(args)
        return result, output.getvalue()

    def test_mode_selection_failures_are_refused_for_all_mode_switching_commands(self):
        cases = (
            (
                "acquire",
                lease.acquire,
                argparse.Namespace(
                    wu="WU-X",
                    actor="worker",
                    branch="feature/x",
                    start_head="a" * 40,
                    pr=1,
                ),
            ),
            (
                "release",
                lease.release,
                argparse.Namespace(lease_id="L1", reason="completed"),
            ),
            (
                "transfer",
                lease.transfer,
                argparse.Namespace(
                    lease_id="L1",
                    actor="worker2",
                    current_head="b" * 40,
                    reason="failover",
                ),
            ),
        )
        for operation, func, args in cases:
            with self.subTest(operation=operation), patch.object(
                lease,
                "ledger_enabled",
                side_effect=RuntimeError("protected tip mismatch"),
            ):
                result, output = self._capture(func, args)
            self.assertEqual(result, 2)
            self.assertIn(
                f"REFUSED: {operation} cannot use coordination safely: protected tip mismatch",
                output,
            )

    def test_coordination_view_failures_are_refused_for_renew_and_reap(self):
        cases = (
            (
                "renew",
                lease.renew,
                argparse.Namespace(lease_id="L1", new_head="b" * 40),
            ),
            (
                "reap",
                lease.reap,
                argparse.Namespace(
                    lease_id=None,
                    actor="system-reaper",
                    reason="lease_expired",
                ),
            ),
        )
        for operation, func, args in cases:
            with (
                self.subTest(operation=operation),
                patch.object(lease, "emergency_stop_active", return_value=False),
                patch.object(
                    lease.lifecycle,
                    "coordination_view",
                    side_effect=RuntimeError("protected tip mismatch"),
                ),
            ):
                result, output = self._capture(func, args)
            self.assertEqual(result, 2)
            self.assertIn(
                f"REFUSED: {operation} cannot use coordination safely: protected tip mismatch",
                output,
            )

    def test_non_runtime_programming_errors_are_not_hidden(self):
        args = argparse.Namespace(
            wu="WU-X",
            actor="worker",
            branch="feature/x",
            start_head="a" * 40,
            pr=1,
        )
        with patch.object(
            lease,
            "ledger_enabled",
            side_effect=ValueError("programming error"),
        ):
            with self.assertRaisesRegex(ValueError, "programming error"):
                lease.acquire(args)


if __name__ == "__main__":
    unittest.main()
