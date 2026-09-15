from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dispatch_execute  # noqa: E402


class DispatchExecutionTests(unittest.TestCase):
    """Regress A3 execution idempotency without enabling unattended mutation."""

    def test_dispatch_identity_is_deterministic_and_lease_bound(self):
        lease = {
            "id": "lease-1",
            "branch": "wu-x",
            "pr": 12,
        }
        first = dispatch_execute.dispatch_identity(
            repository="NTinkicht/OneCompany",
            work_unit="WU-X",
            actor="chatgpt",
            capability="implementation",
            mechanism_id="interactive-connected-chat",
            lease=lease,
        )
        second = dispatch_execute.dispatch_identity(
            repository="NTinkicht/OneCompany",
            work_unit="WU-X",
            actor="chatgpt",
            capability="implementation",
            mechanism_id="interactive-connected-chat",
            lease=dict(lease),
        )
        changed = dispatch_execute.dispatch_identity(
            repository="NTinkicht/OneCompany",
            work_unit="WU-X",
            actor="chatgpt",
            capability="implementation",
            mechanism_id="interactive-connected-chat",
            lease={**lease, "id": "lease-2"},
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_write_dispatch_requires_exact_actor_and_work_unit_lease(self):
        view = {
            "active_leases": [
                {
                    "id": "lease-1",
                    "role": "implementation",
                    "actor": "chatgpt",
                    "work_unit": "WU-X",
                }
            ]
        }
        lease, reasons = dispatch_execute.validate_write_lease(
            view,
            lease_id="lease-1",
            actor="chatgpt",
            work_unit="WU-X",
        )
        self.assertEqual(lease["id"], "lease-1")
        self.assertEqual(reasons, [])

        _, reasons = dispatch_execute.validate_write_lease(
            view,
            lease_id="lease-1",
            actor="other",
            work_unit="WU-Y",
        )
        self.assertIn("lease_actor_mismatch", reasons)
        self.assertIn("lease_work_unit_mismatch", reasons)

        _, reasons = dispatch_execute.validate_write_lease(
            view,
            lease_id="missing",
            actor="chatgpt",
            work_unit="WU-X",
        )
        self.assertEqual(reasons, ["lease_not_canonical_active_and_unexpired"])

    def test_concurrent_replays_start_one_adapter_only(self):
        request = {"dispatch_id": "dispatch-test-concurrent"}
        calls = 0
        calls_lock = threading.Lock()

        def adapter(_request):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.12)
            return {
                "status": "DISPATCH_STARTED",
                "evidence": {"run_id": "run-1"},
            }

        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            results: list[dict] = []

            def worker():
                results.append(
                    dispatch_execute.execute_with_adapter(
                        request,
                        adapter,
                        journal_path=journal,
                    )
                )

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(calls, 1)
            self.assertEqual(
                sorted(result["status"] for result in results),
                ["DISPATCH_ALREADY_ACTIVE", "DISPATCH_STARTED"],
            )
            events = dispatch_execute.load_dispatch_events(journal)
            self.assertEqual(
                [event["state"] for event in events],
                ["DISPATCH_CLAIMED", "DISPATCH_STARTED"],
            )

    def test_successful_adapter_with_unrecorded_outcome_stays_non_retryable(self):
        request = {"dispatch_id": "dispatch-test-unrecorded"}
        calls = 0

        def adapter(_request):
            nonlocal calls
            calls += 1
            return {
                "status": "DISPATCH_STARTED",
                "evidence": {"run_id": "run-unrecorded"},
            }

        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            with patch.object(
                dispatch_execute,
                "record_dispatch_outcome",
                side_effect=RuntimeError("simulated fsync failure"),
            ):
                first = dispatch_execute.execute_with_adapter(
                    request,
                    adapter,
                    journal_path=journal,
                )

            second = dispatch_execute.execute_with_adapter(
                request,
                adapter,
                journal_path=journal,
                retry_failed=True,
            )

            self.assertEqual(first["status"], "DISPATCH_OUTCOME_UNRECORDED")
            self.assertEqual(first["adapter_status"], "DISPATCH_STARTED")
            self.assertEqual(second["status"], "DISPATCH_ALREADY_ACTIVE")
            self.assertEqual(calls, 1)
            events = dispatch_execute.load_dispatch_events(journal)
            self.assertEqual(
                [event["state"] for event in events],
                ["DISPATCH_CLAIMED"],
            )

    def test_outcome_rejects_foreign_attempt_and_invalid_transition(self):
        dispatch_id = "dispatch-test-transition"
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            state, attempt_id, _ = dispatch_execute.claim_dispatch(
                dispatch_id,
                journal_path=journal,
            )
            self.assertEqual(state, "DISPATCH_CLAIMED")
            self.assertIsNotNone(attempt_id)
            assert attempt_id is not None

            with self.assertRaisesRegex(
                RuntimeError,
                "dispatch_outcome_attempt_mismatch",
            ):
                dispatch_execute.record_dispatch_outcome(
                    dispatch_id,
                    "foreign-attempt",
                    "DISPATCH_FAILED_SAFE",
                    {},
                    journal_path=journal,
                )

            with self.assertRaisesRegex(
                RuntimeError,
                "dispatch_outcome_invalid_transition",
            ):
                dispatch_execute.record_dispatch_outcome(
                    dispatch_id,
                    attempt_id,
                    "DISPATCH_COMPLETED",
                    {},
                    journal_path=journal,
                )

            retry_state, _, _ = dispatch_execute.claim_dispatch(
                dispatch_id,
                journal_path=journal,
                retry_failed=True,
            )
            self.assertEqual(retry_state, "DISPATCH_ALREADY_ACTIVE")

    def test_adapter_completion_records_started_then_completed(self):
        request = {"dispatch_id": "dispatch-test-completed"}

        def adapter(_request):
            return {
                "status": "DISPATCH_COMPLETED",
                "evidence": {"run_id": "run-complete"},
            }

        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            result = dispatch_execute.execute_with_adapter(
                request,
                adapter,
                journal_path=journal,
            )
            self.assertEqual(result["status"], "DISPATCH_COMPLETED")
            events = dispatch_execute.load_dispatch_events(journal)
            self.assertEqual(
                [event["state"] for event in events],
                ["DISPATCH_CLAIMED", "DISPATCH_STARTED", "DISPATCH_COMPLETED"],
            )

    def test_stale_lock_recovery_requires_old_and_provably_dead_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            lock_dir = journal.with_name(journal.name + ".lock")
            lock_dir.mkdir()
            metadata = {
                "version": 1,
                "pid": 999999,
                "acquired_at_epoch": time.time() - 60,
                "owner_token": "dead-owner",
            }
            (lock_dir / dispatch_execute.LOCK_METADATA_NAME).write_text(
                json.dumps(metadata),
                encoding="utf-8",
            )

            with patch.object(dispatch_execute, "_pid_alive", return_value=False):
                with dispatch_execute.journal_lock(
                    journal,
                    timeout_seconds=0,
                    stale_after_seconds=1,
                ):
                    current = dispatch_execute._read_lock_metadata(lock_dir)
                    self.assertIsNotNone(current)
                    self.assertEqual(current["pid"], os.getpid())
            self.assertFalse(lock_dir.exists())

    def test_stale_lock_recovery_fails_closed_for_missing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            lock_dir = journal.with_name(journal.name + ".lock")
            lock_dir.mkdir()
            with self.assertRaisesRegex(RuntimeError, "dispatch_journal_locked"):
                with dispatch_execute.journal_lock(
                    journal,
                    timeout_seconds=0,
                    stale_after_seconds=0,
                ):
                    self.fail("invalid lock metadata must not be reclaimed")

    def test_stale_lock_recovery_never_steals_live_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            lock_dir = journal.with_name(journal.name + ".lock")
            lock_dir.mkdir()
            metadata = {
                "version": 1,
                "pid": os.getpid(),
                "acquired_at_epoch": time.time() - 3600,
                "owner_token": "live-owner",
            }
            (lock_dir / dispatch_execute.LOCK_METADATA_NAME).write_text(
                json.dumps(metadata),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "dispatch_journal_locked"):
                with dispatch_execute.journal_lock(
                    journal,
                    timeout_seconds=0,
                    stale_after_seconds=1,
                ):
                    self.fail("a live owner must never be reclaimed based on age")

    def test_lock_is_published_only_after_valid_metadata_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            lock_dir = journal.with_name(journal.name + ".lock")
            original_publish = dispatch_execute._publish_lock
            observed = {"checked": False}

            def checked_publish(staging, final_lock):
                observed["checked"] = True
                self.assertEqual(final_lock, lock_dir)
                self.assertFalse(final_lock.exists())
                metadata = dispatch_execute._read_lock_metadata(staging)
                self.assertIsNotNone(metadata)
                self.assertEqual(metadata["pid"], os.getpid())
                original_publish(staging, final_lock)

            with patch.object(
                dispatch_execute,
                "_publish_lock",
                side_effect=checked_publish,
            ):
                with dispatch_execute.journal_lock(journal):
                    self.assertTrue(lock_dir.exists())
                    self.assertIsNotNone(
                        dispatch_execute._read_lock_metadata(lock_dir)
                    )

            self.assertTrue(observed["checked"])
            self.assertFalse(lock_dir.exists())

    def test_metadata_failure_never_publishes_incomplete_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            lock_dir = journal.with_name(journal.name + ".lock")
            with patch.object(
                dispatch_execute,
                "_write_lock_metadata",
                side_effect=RuntimeError("metadata write failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "metadata write failed"):
                    with dispatch_execute.journal_lock(journal):
                        self.fail("metadata failure must prevent lock publication")

            self.assertFalse(lock_dir.exists())
            self.assertEqual(
                list(Path(directory).glob("dispatch-events.jsonl.lock.staging-*")),
                [],
            )

    def test_malformed_journal_event_fails_closed_before_second_claim(self):
        dispatch_id = "dispatch-test-malformed"
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            state, attempt_id, _ = dispatch_execute.claim_dispatch(
                dispatch_id,
                journal_path=journal,
            )
            self.assertEqual(state, "DISPATCH_CLAIMED")
            self.assertIsNotNone(attempt_id)
            assert attempt_id is not None

            malformed = {
                "version": 1,
                "event_id": "malformed-event",
                "dispatch_id": dispatch_id,
                "attempt_id": attempt_id,
                "timestamp": dispatch_execute.utc_now(),
                "evidence": {},
            }
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(malformed) + "\n")

            with self.assertRaisesRegex(RuntimeError, "invalid state"):
                dispatch_execute.claim_dispatch(
                    dispatch_id,
                    journal_path=journal,
                    retry_failed=True,
                )

            self.assertEqual(len(journal.read_text(encoding="utf-8").splitlines()), 2)

    def test_unknown_journal_state_fails_closed_before_second_claim(self):
        dispatch_id = "dispatch-test-unknown-state"
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            state, attempt_id, _ = dispatch_execute.claim_dispatch(
                dispatch_id,
                journal_path=journal,
            )
            self.assertEqual(state, "DISPATCH_CLAIMED")
            assert attempt_id is not None

            malformed = {
                "version": 1,
                "event_id": "unknown-state-event",
                "dispatch_id": dispatch_id,
                "attempt_id": attempt_id,
                "state": "DISPATCH_MAYBE",
                "timestamp": dispatch_execute.utc_now(),
                "evidence": {},
            }
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(malformed) + "\n")

            with self.assertRaisesRegex(RuntimeError, "unknown state"):
                dispatch_execute.claim_dispatch(
                    dispatch_id,
                    journal_path=journal,
                    retry_failed=True,
                )

    def test_failed_start_is_safe_and_not_retried_implicitly(self):
        request = {"dispatch_id": "dispatch-test-failure"}
        calls = 0

        def failing_adapter(_request):
            nonlocal calls
            calls += 1
            raise RuntimeError("simulated start failure")

        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            first = dispatch_execute.execute_with_adapter(
                request,
                failing_adapter,
                journal_path=journal,
            )
            second = dispatch_execute.execute_with_adapter(
                request,
                failing_adapter,
                journal_path=journal,
            )

            self.assertEqual(first["status"], "DISPATCH_FAILED_SAFE")
            self.assertEqual(second["status"], "DISPATCH_FAILED_SAFE")
            self.assertEqual(calls, 1)
            self.assertIn("simulated start failure", first["evidence"]["error"])

    def test_failed_start_can_retry_only_when_explicit(self):
        request = {"dispatch_id": "dispatch-test-retry"}
        calls = 0

        def adapter(_request):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("first attempt fails")
            return {
                "status": "DISPATCH_STARTED",
                "evidence": {"run_id": "run-2"},
            }

        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            first = dispatch_execute.execute_with_adapter(
                request,
                adapter,
                journal_path=journal,
            )
            blocked_retry = dispatch_execute.execute_with_adapter(
                request,
                adapter,
                journal_path=journal,
            )
            explicit_retry = dispatch_execute.execute_with_adapter(
                request,
                adapter,
                journal_path=journal,
                retry_failed=True,
            )

            self.assertEqual(first["status"], "DISPATCH_FAILED_SAFE")
            self.assertEqual(blocked_retry["status"], "DISPATCH_FAILED_SAFE")
            self.assertEqual(explicit_retry["status"], "DISPATCH_STARTED")
            self.assertEqual(calls, 2)

    def test_current_chatgpt_planning_mechanism_stays_attended(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "onecompany.py"),
                "execute-dispatch",
                "--actor",
                "chatgpt",
                "--capability",
                "planning",
                "--mechanism",
                "interactive-connected-chat",
                "--work-unit",
                "WU-A3-TEST",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "DISPATCH_ATTENDED_REQUIRED")
        self.assertFalse(payload["mechanism"]["unattended"])
        self.assertIsNone(payload["lease_id"])

    def test_current_chatgpt_write_cannot_execute_without_lease(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "onecompany.py"),
                "execute-dispatch",
                "--actor",
                "chatgpt",
                "--capability",
                "implementation",
                "--mechanism",
                "interactive-connected-chat",
                "--work-unit",
                "WU-A3-TEST",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "CAPACITY_BLOCKED")
        self.assertIn(
            "active_lease_id_required_for_write_dispatch",
            payload["reasons"],
        )


if __name__ == "__main__":
    unittest.main()
