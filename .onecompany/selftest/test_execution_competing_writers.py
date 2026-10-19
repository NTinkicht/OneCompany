"""OC-P0-04 (#322): 100+ competing execution writers across real processes.

Every writer is a separate ``python scripts/execution.py`` process sharing one
temporary runtime root, so the per-WU OS file lock and the exact RunKey
generation fence are exercised exactly as unattended actors use them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from execution_core import ExecutionJournal, ExecutionStore  # noqa: E402

CLI = ROOT / "scripts" / "execution.py"
WU = "WU-OC-P0-04"
RUN_ID = "run-competing"
WRITERS = 120
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def holds_open(pid: int, path: Path) -> bool:
    """Whether a live process has ``path`` open (Linux /proc)."""
    try:
        fds = list(Path(f"/proc/{pid}/fd").iterdir())
    except OSError:
        return False
    for fd in fds:
        try:
            if Path(os.readlink(fd)) == path:
                return True
        except OSError:
            continue
    return False


class CompetingExecutionWritersTest(unittest.TestCase):
    """Zero double writers and zero lost updates under real contention."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        created = self.run_cli(
            "create",
            "--wu",
            WU,
            "--run-id",
            RUN_ID,
            "--objective",
            "Competing writer baseline",
            "--acceptance-criterion",
            "AC1=one generation winner",
        )
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def command(self, subcommand: str, *args: str) -> list[str]:
        return [
            sys.executable,
            str(CLI),
            "--runtime-root",
            str(self.root),
            subcommand,
            *args,
        ]

    def run_cli(self, subcommand: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.command(subcommand, *args),
            capture_output=True,
            text=True,
            timeout=120,
            env=ENV,
            check=False,
        )

    @staticmethod
    def fenced_args(subcommand: str, generation: int, *args: str) -> tuple[str, ...]:
        return (
            subcommand,
            "--wu",
            WU,
            "--run-id",
            RUN_ID,
            "--generation",
            str(generation),
            *args,
        )

    def fenced(self, subcommand: str, generation: int, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli(*self.fenced_args(subcommand, generation, *args))

    def compete(self, make_args) -> list[subprocess.CompletedProcess[str]]:
        """Start every writer while the test holds the WU lock, then release.

        On Linux the gate also waits until every child has opened the lock
        file, i.e. is queued on the same lock, so the race always has real
        overlap even on a slow or single-core runner.
        """
        store = ExecutionStore(self.root)
        lock_path = store.lock_path(WU).resolve()
        with store.lock(WU):
            children = [
                subprocess.Popen(
                    self.command(*make_args(index)),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=ENV,
                )
                for index in range(WRITERS)
            ]
            if Path("/proc/self/fd").is_dir():
                deadline = time.monotonic() + 90
                waiting = {child.pid for child in children}
                while waiting and time.monotonic() < deadline:
                    waiting = {
                        pid for pid in waiting if not holds_open(pid, lock_path)
                    }
                    if waiting:
                        time.sleep(0.05)
                self.assertEqual(
                    waiting, set(), "writers never queued on the WU lock"
                )
                self.assertTrue(
                    all(child.poll() is None for child in children),
                    "a writer finished while the WU lock was held",
                )
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=120)
            results.append(
                subprocess.CompletedProcess(
                    child.args, child.returncode, stdout, stderr
                )
            )
        return results

    def journal(self) -> list[dict]:
        store = ExecutionStore(self.root)
        return ExecutionJournal.verify(store.journal_path(WU))

    def state(self) -> dict:
        shown = self.run_cli("show", "--wu", WU)
        self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
        return json.loads(shown.stdout)

    def assert_stale_rejection(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertIn("stale execution key", payload["error"])

    def test_exactly_one_of_many_generation_rotations_wins(self) -> None:
        results = self.compete(
            lambda index: self.fenced_args(
                "edit", 1, "--objective", f"Revision from writer {index}"
            )
        )

        winners = [result for result in results if result.returncode == 0]
        self.assertEqual(len(winners), 1, [r.stdout for r in winners])
        for result in results:
            if result.returncode != 0:
                self.assert_stale_rejection(result)

        state = self.state()
        self.assertEqual(state["key"]["generation"], 2)
        self.assertEqual(
            state["objective"], json.loads(winners[0].stdout)["objective"]
        )
        events = [record["event_type"] for record in self.journal()]
        self.assertEqual(events.count("objective_revised"), 1)
        self.assertEqual(len(events), 2)

    def test_many_same_generation_writes_are_serialized_without_loss(self) -> None:
        results = self.compete(
            lambda index: self.fenced_args(
                "task-add",
                1,
                "--task-id",
                f"T{index:03d}",
                "--description",
                f"task from writer {index}",
            )
        )

        failures = [r.stdout + r.stderr for r in results if r.returncode != 0]
        self.assertEqual(failures, [])
        state = self.state()
        self.assertEqual(state["key"]["generation"], 1)
        self.assertEqual(
            set(state["tasks"]), {f"T{index:03d}" for index in range(WRITERS)}
        )
        records = self.journal()
        self.assertEqual(len(records), 1 + WRITERS)
        self.assertEqual(
            [record["sequence"] for record in records],
            list(range(1, WRITERS + 2)),
        )
        self.assertEqual(
            len({record["operation_id"] for record in records}), len(records)
        )

    def test_stale_generation_replay_after_restart_changes_nothing(self) -> None:
        rotated = self.fenced("edit", 1, "--objective", "Generation two")
        self.assertEqual(rotated.returncode, 0, rotated.stdout + rotated.stderr)

        # A fresh store (process restart) reconstructs the same fenced state.
        reloaded = ExecutionStore(self.root).load(WU)
        self.assertEqual(reloaded.key.generation, 2)
        store = ExecutionStore(self.root)
        before_state = self.state()
        before_bytes = (
            store.state_path(WU).read_bytes(),
            store.journal_path(WU).read_bytes(),
        )

        for replay in (
            self.fenced("task-add", 1, "--task-id", "late", "--description", "late"),
            self.fenced("edit", 1, "--objective", "Late generation-one revision"),
        ):
            self.assert_stale_rejection(replay)

        self.assertEqual(self.state(), before_state)
        self.assertEqual(
            (
                store.state_path(WU).read_bytes(),
                store.journal_path(WU).read_bytes(),
            ),
            before_bytes,
        )


if __name__ == "__main__":
    unittest.main()
