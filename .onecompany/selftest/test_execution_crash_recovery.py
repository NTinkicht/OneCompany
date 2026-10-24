"""OC-P0-04 (#328): crash-point recovery and fail-closed orphan vectors.

``ExecutionStore.persist_event`` writes a write-ahead marker, then state, then
one journal record, then clears the marker. These tests interrupt each step
(in-process and by killing a real process) and prove that recovery commits
exactly one journal record per operation, and that corrupt or orphaned
artifacts fail closed without being silently repaired.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from execution_core import (  # noqa: E402
    ExecutionJournal,
    ExecutionStore,
    JournalIntegrityError,
    RunContext,
)

WU = "WU-OC-P0-04-CRASH"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def baseline() -> RunContext:
    """Generation-one context used as the committed revision."""
    return RunContext.new(
        WU,
        "Crash recovery baseline",
        {"AC1": "exactly one record per operation"},
        run_id="run-crash",
    )


def revised(context: RunContext, objective: str) -> RunContext:
    """Return a distinct next revision of ``context``."""
    copy = RunContext.from_dict(context.to_dict())
    copy.objective = objective
    copy.updated_at = context.updated_at + 1
    return copy


class CrashRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = ExecutionStore(self.root)
        self.first = baseline()
        self.store.persist_event(self.first, "created")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def records(self) -> list[dict]:
        return ExecutionJournal.verify(self.store.journal_path(WU))

    def snapshot(self) -> dict[str, bytes]:
        """Every durable artifact except the OS lock file."""
        return {
            path.name: path.read_bytes()
            for path in sorted(self.root.iterdir())
            if path.is_file() and not path.name.endswith(".lock")
        }

    def assert_recovered(self, intended: RunContext) -> None:
        loaded = self.store.load(WU)
        self.assertEqual(loaded.to_dict(), intended.to_dict())
        self.assertFalse(self.store.pending_path(WU).exists())
        records = self.records()
        self.assertEqual([r["sequence"] for r in records], [1, 2])
        self.assertEqual(len({r["operation_id"] for r in records}), 2)
        self.assertEqual(
            records[-1]["state_hash"],
            ExecutionJournal.canonical_hash(intended.to_dict()),
        )
        # Recovery is idempotent: a second load changes nothing on disk.
        before = self.snapshot()
        self.store.load(WU)
        self.assertEqual(self.snapshot(), before)

    def crash(self, target: object, attribute: str) -> RunContext:
        """Persist a revision with ``attribute`` failing like a crash."""
        intended = revised(self.first, "Revision interrupted by a crash")
        with patch.object(
            target, attribute, side_effect=OSError("simulated crash")
        ):
            with self.assertRaises(OSError):
                self.store.persist_event(intended, "objective_revised")
        self.assertTrue(self.store.pending_path(WU).exists())
        return intended

    def test_crash_after_marker_before_state_write(self) -> None:
        intended = self.crash(ExecutionStore, "save")
        on_disk = json.loads(
            self.store.state_path(WU).read_text(encoding="utf-8")
        )
        self.assertEqual(on_disk["objective"], self.first.objective)
        self.assert_recovered(intended)

    def test_crash_after_state_before_journal_commit(self) -> None:
        intended = self.crash(ExecutionJournal, "append")
        self.assertEqual(len(self.records()), 1)
        self.assert_recovered(intended)

    def test_crash_after_journal_commit_before_marker_clear(self) -> None:
        intended = self.crash(ExecutionStore, "_clear_pending")
        # Already committed: recovery must not append a duplicate record.
        self.assertEqual(len(self.records()), 2)
        self.assert_recovered(intended)

    def test_killed_process_recovers_in_a_fresh_process(self) -> None:
        script = textwrap.dedent(
            f"""
            import os, sys
            from pathlib import Path
            sys.path.insert(0, {str(ROOT / "scripts")!r})
            from execution_core import ExecutionJournal, ExecutionStore
            store = ExecutionStore(Path(sys.argv[1]))
            context = store.load({WU!r})
            context.objective = "Revision from a killed process"
            context.updated_at += 1
            ExecutionJournal.append = lambda *a, **k: os._exit(17)
            store.persist_event(context, "objective_revised")
            """
        )
        killed = subprocess.run(
            [sys.executable, "-c", script, str(self.root)],
            env=ENV,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(killed.returncode, 17, killed.stderr)
        self.assertTrue(self.store.pending_path(WU).exists())

        recover = textwrap.dedent(
            f"""
            import json, sys
            from pathlib import Path
            sys.path.insert(0, {str(ROOT / "scripts")!r})
            from execution_core import ExecutionStore
            print(json.dumps(ExecutionStore(Path(sys.argv[1])).load({WU!r}).to_dict()))
            """
        )
        fresh = subprocess.run(
            [sys.executable, "-c", recover, str(self.root)],
            env=ENV,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        recovered = RunContext.from_dict(json.loads(fresh.stdout))
        self.assertEqual(recovered.objective, "Revision from a killed process")
        self.assert_recovered(recovered)

        follow_up = revised(recovered, "Write after recovery")
        self.store.persist_event(follow_up, "objective_revised")
        self.assertEqual(
            [r["sequence"] for r in self.records()], [1, 2, 3]
        )
        self.assertEqual(self.store.load(WU).to_dict(), follow_up.to_dict())

    def assert_fails_closed(self) -> None:
        before = self.snapshot()
        with self.assertRaises(JournalIntegrityError):
            self.store.load(WU)
        with self.assertRaises(JournalIntegrityError):
            self.store.persist_event(
                revised(self.first, "must not be written"), "objective_revised"
            )
        self.assertEqual(self.snapshot(), before)

    def test_torn_marker_fails_closed(self) -> None:
        self.store.pending_path(WU).write_text('{"operation_id": "ab', "utf-8")
        self.assert_fails_closed()

    def test_marker_for_another_work_unit_fails_closed(self) -> None:
        other = RunContext.new(
            "WU-OTHER", "Other unit", {"AC1": "x"}, run_id="run-other"
        )
        self.store.pending_path(WU).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "operation_id": "f" * 32,
                    "event_type": "created",
                    "details": {},
                    "recorded_at": 1.0,
                    "context": other.to_dict(),
                }
            ),
            "utf-8",
        )
        self.assert_fails_closed()

    def test_stale_committed_marker_fails_closed(self) -> None:
        intended = self.crash(ExecutionStore, "_clear_pending")
        stale_marker = self.store.pending_path(WU).read_bytes()
        self.store.load(WU)  # acknowledges and clears the marker
        self.store.persist_event(revised(intended, "Later write"), "objective_revised")
        # A resurrected marker for an operation that is committed but no
        # longer the latest record must not roll state back.
        self.store.pending_path(WU).write_bytes(stale_marker)
        self.assert_fails_closed()

    def test_torn_journal_tail_fails_closed_without_repair(self) -> None:
        journal = self.store.journal_path(WU)
        with journal.open("a", encoding="utf-8") as handle:
            handle.write('{"sequence":2,"event_type":"objective_rev')
        self.assert_fails_closed()
        with self.assertRaises(JournalIntegrityError):
            ExecutionJournal.append(
                journal, event_type="objective_revised", context=self.first
            )
        self.assertTrue(
            journal.read_text(encoding="utf-8").endswith("objective_rev")
        )


if __name__ == "__main__":
    unittest.main()
