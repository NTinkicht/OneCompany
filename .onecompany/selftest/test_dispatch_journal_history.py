from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dispatch_execute  # noqa: E402


class DispatchJournalHistoryTests(unittest.TestCase):
    """Regress whole-history corruption paths that could duplicate workers."""

    def test_foreign_terminal_event_after_active_claim_fails_closed(self):
        dispatch_id = "dispatch-history-foreign-terminal"
        request = {"dispatch_id": dispatch_id}
        calls = 0

        def adapter(_request):
            nonlocal calls
            calls += 1
            return {
                "status": "DISPATCH_STARTED",
                "evidence": {"run_id": "must-not-start"},
            }

        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            state, attempt_id, _ = dispatch_execute.claim_dispatch(
                dispatch_id,
                journal_path=journal,
            )
            self.assertEqual(state, "DISPATCH_CLAIMED")
            self.assertIsNotNone(attempt_id)

            forged_failure = {
                "version": 1,
                "event_id": "forged-terminal-event",
                "dispatch_id": dispatch_id,
                "attempt_id": "foreign-attempt",
                "state": "DISPATCH_FAILED_SAFE",
                "timestamp": dispatch_execute.utc_now(),
                "evidence": {"error": "forged"},
            }
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(forged_failure) + "\n")

            with self.assertRaisesRegex(RuntimeError, "history attempt mismatch"):
                dispatch_execute.execute_with_adapter(
                    request,
                    adapter,
                    journal_path=journal,
                    retry_failed=True,
                )

            self.assertEqual(calls, 0)

    def test_retry_claim_requires_valid_failed_terminal_history(self):
        dispatch_id = "dispatch-history-invalid-retry"
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "dispatch-events.jsonl"
            state, attempt_id, _ = dispatch_execute.claim_dispatch(
                dispatch_id,
                journal_path=journal,
            )
            self.assertEqual(state, "DISPATCH_CLAIMED")
            assert attempt_id is not None

            dispatch_execute.record_dispatch_outcome(
                dispatch_id,
                attempt_id,
                "DISPATCH_FAILED_SAFE",
                {"error": "real failure"},
                journal_path=journal,
            )

            forged_retry = {
                "version": 1,
                "event_id": "forged-retry-event",
                "dispatch_id": dispatch_id,
                "attempt_id": "new-attempt",
                "state": "DISPATCH_CLAIMED",
                "timestamp": dispatch_execute.utc_now(),
                "evidence": {"retry_failed": False},
            }
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(forged_retry) + "\n")

            with self.assertRaisesRegex(
                RuntimeError,
                "retry lacks explicit retry evidence",
            ):
                dispatch_execute.load_dispatch_events(journal)


if __name__ == "__main__":
    unittest.main()
