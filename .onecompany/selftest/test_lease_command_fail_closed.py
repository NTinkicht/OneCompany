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
    """Lease commands distinguish safe refusal from mutation uncertainty."""

    def _capture(self, func, args):
        output = io.StringIO()
        with redirect_stdout(output):
            result = func(args)
        return result, output.getvalue()

    @staticmethod
    def _args(operation: str):
        if operation == "acquire":
            return argparse.Namespace(
                wu="WU-X",
                actor="worker",
                branch="feature/x",
                start_head="a" * 40,
                pr=1,
            )
        if operation == "release":
            return argparse.Namespace(lease_id="L1", reason="completed")
        if operation == "transfer":
            return argparse.Namespace(
                lease_id="L1",
                actor="worker2",
                current_head="b" * 40,
                reason="failover",
            )
        if operation == "renew":
            return argparse.Namespace(lease_id="L1", new_head="b" * 40)
        if operation == "reap":
            return argparse.Namespace(
                lease_id=None,
                actor="system-reaper",
                reason="lease_expired",
            )
        raise AssertionError(operation)

    def test_pre_mutation_mode_selection_failures_are_refused(self):
        for operation, func in (
            ("acquire", lease.acquire),
            ("release", lease.release),
            ("transfer", lease.transfer),
        ):
            with self.subTest(operation=operation), patch.object(
                lease,
                "ledger_enabled",
                side_effect=RuntimeError("protected tip mismatch"),
            ):
                result, output = self._capture(func, self._args(operation))
            self.assertEqual(result, 2)
            self.assertIn(
                f"REFUSED: {operation} cannot use coordination safely: protected tip mismatch",
                output,
            )

    def test_pre_mutation_view_failures_are_refused_for_renew_and_reap(self):
        for operation, func in (
            ("renew", lease.renew),
            ("reap", lease.reap),
        ):
            with (
                self.subTest(operation=operation),
                patch.object(lease, "emergency_stop_active", return_value=False),
                patch.object(
                    lease.lifecycle,
                    "coordination_view",
                    side_effect=RuntimeError("protected tip mismatch"),
                ),
            ):
                result, output = self._capture(func, self._args(operation))
            self.assertEqual(result, 2)
            self.assertIn(
                f"REFUSED: {operation} cannot use coordination safely: protected tip mismatch",
                output,
            )

    def test_core_refusal_after_publication_attempt_is_indeterminate(self):
        def mutate_then_refuse(_args):
            lease.core.post_event(
                "ROLE_LEASE_ASSIGNED",
                "worker",
                {"lease_id": "L1"},
            )
            return 2

        for operation, func in (
            ("acquire", lease.acquire),
            ("release", lease.release),
            ("transfer", lease.transfer),
        ):
            with (
                self.subTest(operation=operation),
                patch.object(lease, "ledger_enabled", return_value=True),
                patch.object(lease, "post_event", return_value={}),
                patch.object(lease.core, operation, side_effect=mutate_then_refuse),
            ):
                result, output = self._capture(func, self._args(operation))
            self.assertEqual(result, 3)
            self.assertIn("INDETERMINATE:", output)
            self.assertIn("reconcile before retry", output)

    def test_post_core_success_cache_failure_is_indeterminate(self):
        def mutate_then_succeed(_args):
            lease.core.post_event(
                "ROLE_LEASE_ASSIGNED",
                "worker",
                {"lease_id": "L1"},
            )
            return 0

        for operation, func in (
            ("acquire", lease.acquire),
            ("release", lease.release),
            ("transfer", lease.transfer),
        ):
            with (
                self.subTest(operation=operation),
                patch.object(lease, "ledger_enabled", return_value=True),
                patch.object(lease, "post_event", return_value={}),
                patch.object(lease.core, operation, side_effect=mutate_then_succeed),
                patch.object(
                    lease,
                    "_reconcile_cache",
                    side_effect=RuntimeError("replay failed"),
                ),
            ):
                result, output = self._capture(func, self._args(operation))
            self.assertEqual(result, 3)
            self.assertIn("INDETERMINATE:", output)
            self.assertIn("reconcile before retry", output)

    def test_post_append_failures_are_indeterminate_for_renew_and_reap(self):
        active_lease = {
            "id": "L1",
            "actor": "worker",
            "pr": 7,
            "start_head": "a" * 40,
            "last_progress_head": "a" * 40,
        }
        with (
            patch.object(lease, "emergency_stop_active", return_value=False),
            patch.object(lease, "_active_view", return_value=({}, [active_lease])),
            patch.object(lease, "ledger_enabled", return_value=False),
            patch.object(lease.lifecycle, "append_coordination_event", return_value={}),
            patch.object(
                lease.lifecycle,
                "coordination_view",
                side_effect=RuntimeError("post-renew replay failed"),
            ),
        ):
            result, output = self._capture(lease.renew, self._args("renew"))
        self.assertEqual(result, 3)
        self.assertIn("INDETERMINATE:", output)
        self.assertIn("reconcile before retry", output)

        expired = {"id": "L1"}
        with (
            patch.object(
                lease.lifecycle,
                "coordination_view",
                side_effect=[
                    {"expired_leases": [expired]},
                    RuntimeError("post-reap replay failed"),
                ],
            ),
            patch.object(lease.lifecycle, "append_coordination_event", return_value={}),
            patch.object(lease.lifecycle, "reap_payload", return_value={}),
        ):
            result, output = self._capture(lease.reap, self._args("reap"))
        self.assertEqual(result, 3)
        self.assertIn("INDETERMINATE:", output)
        self.assertIn("reconcile before retry", output)

    def test_pre_mutation_core_refusal_remains_retry_safe_refusal(self):
        for operation, func in (
            ("acquire", lease.acquire),
            ("release", lease.release),
            ("transfer", lease.transfer),
        ):
            with (
                self.subTest(operation=operation),
                patch.object(lease, "ledger_enabled", return_value=True),
                patch.object(lease.core, operation, return_value=2),
            ):
                result, output = self._capture(func, self._args(operation))
            self.assertEqual(result, 2)
            self.assertNotIn("INDETERMINATE:", output)

    def test_non_runtime_programming_errors_are_not_hidden(self):
        with patch.object(
            lease,
            "ledger_enabled",
            side_effect=ValueError("programming error"),
        ):
            with self.assertRaisesRegex(ValueError, "programming error"):
                lease.acquire(self._args("acquire"))


if __name__ == "__main__":
    unittest.main()
