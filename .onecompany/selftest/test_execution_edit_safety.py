from __future__ import annotations

import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import execution as execution_cli
from execution_core import ExecutionStore, ResourceBudget, RunContext


class ExecutionEditSafetyTests(unittest.TestCase):
    """Keep objective edits from rotating generation without a real change."""

    def test_empty_edit_is_rejected_without_generation_rotation(self) -> None:
        """Reject a no-op edit and preserve the exact current RunKey."""
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            existing = RunContext.new(
                "WU-EDIT-SAFE",
                "original objective",
                {"AC1": "preserve generation"},
                ResourceBudget(),
                run_id="run-original",
            )
            store.persist_event(existing, "created")

            args = Namespace(
                runtime_root=directory,
                wu="WU-EDIT-SAFE",
                run_id="run-original",
                generation=1,
                objective=None,
                acceptance_criterion=None,
            )
            with self.assertRaises(ValueError):
                execution_cli.cmd_edit(args)

            preserved = store.load("WU-EDIT-SAFE")
            self.assertEqual(preserved.key.generation, 1)
            self.assertEqual(preserved.key.run_id, "run-original")
            self.assertEqual(preserved.objective, "original objective")


if __name__ == "__main__":
    unittest.main()
