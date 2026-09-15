from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

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
