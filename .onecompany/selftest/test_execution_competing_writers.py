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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from execution_core import ExecutionJournal, ExecutionStore  # noqa: E402

CLI = ROOT / "scripts" / "execution.py"
WU = "WU-OC-P0-04"
RUN_ID = "run-competing"
WRITERS = 120


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

    def run_cli(self, subcommand: str, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--runtime-root",
                str(self.root),
                subcommand,
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            check=False,
        )

    def fenced(self, subcommand: str, generation: int, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            subcommand,
            "--wu",
            WU,
            "--run-id",
            RUN_ID,
            "--generation",
            str(generation),
            *args,
        )

    def compete(self, make_args) -> list[subprocess.CompletedProcess[str]]:
        with ThreadPoolExecutor(max_workers=WRITERS) as pool:
            return list(pool.map(make_args, range(WRITERS)))

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
            lambda index: self.fenced(
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
            lambda index: self.fenced(
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
        before_state = self.state()
        before_journal = self.journal()

        for replay in (
            self.fenced("task-add", 1, "--task-id", "late", "--description", "late"),
            self.fenced("edit", 1, "--objective", "Late generation-one revision"),
        ):
            self.assert_stale_rejection(replay)

        self.assertEqual(self.state(), before_state)
        self.assertEqual(self.journal(), before_journal)


if __name__ == "__main__":
    unittest.main()
