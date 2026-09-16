from __future__ import annotations

import argparse
import io
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
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

    def _run_local_append_failure(self, operation: str, error: Exception):
        func = getattr(lease, operation)
        old = {
            "id": "L1",
            "actor": "worker",
            "work_unit": "WU-X",
            "branch": "feature/x",
            "pr": 1,
            "start_head": "a" * 40,
            "last_progress_head": "a" * 40,
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(lease, "ledger_enabled", return_value=False))
            stack.enter_context(patch.object(lease, "append_local_event", side_effect=error))

            if operation == "acquire":
                stack.enter_context(
                    patch.object(lease, "emergency_stop_active", return_value=False)
                )
                stack.enter_context(
                    patch.object(
                        lease,
                        "load_json",
                        side_effect=[
                            {"work_units": [{"id": "WU-X", "status": "READY"}]},
                            {"parallel_execution": {"max_concurrent_implementation_streams": 1}},
                        ],
                    )
                )
                stack.enter_context(
                    patch.object(
                        lease,
                        "_active_view",
                        return_value=({"verified_merged_work_units": []}, []),
                    )
                )
                stack.enter_context(
                    patch.object(
                        lease,
                        "_local_dependency_check",
                        return_value=(True, [], []),
                    )
                )
                stack.enter_context(
                    patch.object(
                        lease,
                        "actor_capacity_state",
                        return_value=(1, [], 0, 1),
                    )
                )
                stack.enter_context(
                    patch.object(lease, "implementation_admission_violations", return_value=[])
                )
                stack.enter_context(patch.object(lease, "new_lease", return_value={"id": "L1"}))
                stack.enter_context(
                    patch.object(lease, "lease_payload", return_value={"lease_id": "L1"})
                )
            elif operation == "release":
                stack.enter_context(patch.object(lease, "_active_view", return_value=({}, [old])))
            elif operation == "transfer":
                stack.enter_context(
                    patch.object(lease, "emergency_stop_active", return_value=False)
                )
                stack.enter_context(patch.object(lease, "_active_view", return_value=({}, [old])))
                stack.enter_context(
                    patch.object(
                        lease,
                        "load_json",
                        side_effect=[{"work_units": []}, {}],
                    )
                )
                stack.enter_context(
                    patch.object(
                        lease,
                        "actor_capacity_state",
                        return_value=(1, [], 0, 1),
                    )
                )
                stack.enter_context(
                    patch.object(lease, "work_item_for_lease", return_value={"id": "WU-X"})
                )
                stack.enter_context(
                    patch.object(lease, "implementation_admission_violations", return_value=[])
                )
                stack.enter_context(patch.object(lease, "new_lease", return_value={"id": "L2"}))
                stack.enter_context(patch.object(lease, "lease_payload", return_value={}))
            elif operation == "renew":
                stack.enter_context(
                    patch.object(lease, "emergency_stop_active", return_value=False)
                )
                stack.enter_context(patch.object(lease, "_active_view", return_value=({}, [old])))
                stack.enter_context(
                    patch.object(lease.lifecycle, "renewal_payload", return_value={})
                )
            elif operation == "reap":
                stack.enter_context(
                    patch.object(
                        lease.lifecycle,
                        "coordination_view",
                        return_value={"expired_leases": [old]},
                    )
                )
                stack.enter_context(
                    patch.object(lease.lifecycle, "reap_payload", return_value={})
                )
            else:
                raise AssertionError(operation)

            return self._capture(func, self._args(operation))

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

    def test_local_pre_mutation_oserror_is_ordinary_failure_across_operations(self):
        for operation in ("acquire", "release", "transfer", "renew", "reap"):
            with self.subTest(operation=operation):
                result, output = self._run_local_append_failure(
                    operation,
                    OSError("mkdir/open failed"),
                )
            self.assertEqual(result, 1)
            self.assertIn(f"ERROR: {operation} failed before mutation", output)
            self.assertNotIn("INDETERMINATE:", output)

    def test_local_pre_mutation_runtime_error_is_refused_across_operations(self):
        for operation in ("acquire", "release", "transfer", "renew", "reap"):
            with self.subTest(operation=operation):
                result, output = self._run_local_append_failure(
                    operation,
                    RuntimeError("local log corrupt before append"),
                )
            self.assertEqual(result, 2)
            self.assertIn(f"REFUSED: {operation} cannot use coordination safely", output)
            self.assertNotIn("INDETERMINATE:", output)

    def test_local_write_uncertainty_is_indeterminate_across_operations(self):
        for operation in ("acquire", "release", "transfer", "renew", "reap"):
            with self.subTest(operation=operation):
                result, output = self._run_local_append_failure(
                    operation,
                    lease.LocalEventMutationUncertainError("write may have landed"),
                )
            self.assertEqual(result, 3)
            self.assertIn("INDETERMINATE:", output)
            self.assertIn("reconcile before retry", output)

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

    def test_post_mutation_oserror_is_indeterminate_across_operations(self):
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
                    side_effect=OSError("disk full"),
                ),
            ):
                result, output = self._capture(func, self._args(operation))
            self.assertEqual(result, 3)
            self.assertIn("INDETERMINATE:", output)
            self.assertIn("reconcile before retry", output)

        active_lease = {
            "id": "L1",
            "actor": "worker",
            "pr": 7,
            "start_head": "a" * 40,
            "last_progress_head": "a" * 40,
        }
        renewed_lease = {
            **active_lease,
            "last_progress_head": "b" * 40,
        }
        with (
            patch.object(lease, "emergency_stop_active", return_value=False),
            patch.object(lease, "_active_view", return_value=({}, [active_lease])),
            patch.object(lease, "ledger_enabled", return_value=False),
            patch.object(lease, "append_local_event", return_value={}),
            patch.object(
                lease.lifecycle,
                "coordination_view",
                return_value={"active_leases": [renewed_lease]},
            ),
            patch.object(
                lease,
                "_reconcile_cache",
                side_effect=OSError("disk full"),
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
                    {"expired_leases": []},
                ],
            ),
            patch.object(lease, "ledger_enabled", return_value=False),
            patch.object(lease, "append_local_event", return_value={}),
            patch.object(lease.lifecycle, "reap_payload", return_value={}),
            patch.object(
                lease,
                "_reconcile_cache",
                side_effect=OSError("disk full"),
            ),
        ):
            result, output = self._capture(lease.reap, self._args("reap"))
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
            patch.object(lease, "append_local_event", return_value={}),
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
            patch.object(lease, "ledger_enabled", return_value=False),
            patch.object(lease, "append_local_event", return_value={}),
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
