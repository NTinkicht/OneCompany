from __future__ import annotations

import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import execution as execution_cli
from execution_core import ExecutionStore


class ExecutionCreateArtifactGuardTests(unittest.TestCase):
    """Creation must fail closed when any prior execution artifact remains."""

    def args(self, runtime_root: str) -> Namespace:
        return Namespace(
            runtime_root=runtime_root,
            wu="WU-ARTIFACT-GUARD",
            objective="guard creation lineage",
            acceptance_criterion=[("AC1", "lineage is preserved")],
            max_tokens=None,
            max_active_seconds=None,
            max_errors=None,
            max_unchanged=None,
            run_id="run-new",
        )

    def test_create_rejects_orphaned_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            journal = store.journal_path("WU-ARTIFACT-GUARD")
            journal.parent.mkdir(parents=True, exist_ok=True)
            journal.write_text('{"orphaned":true}\n', encoding="utf-8")

            with self.assertRaises(FileExistsError):
                execution_cli.cmd_create(self.args(directory))

    def test_create_rejects_orphaned_pending_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            pending = store.pending_path("WU-ARTIFACT-GUARD")
            pending.parent.mkdir(parents=True, exist_ok=True)
            pending.write_text('{"orphaned":true}\n', encoding="utf-8")

            with self.assertRaises(FileExistsError):
                execution_cli.cmd_create(self.args(directory))


if __name__ == "__main__":
    unittest.main()
