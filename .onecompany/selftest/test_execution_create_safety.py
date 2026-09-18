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


class ExecutionCreateSafetyTests(unittest.TestCase):
    """Keep execution creation fail-closed when a work unit already exists."""

    def test_create_parser_rejects_replace_flag(self) -> None:
        """Do not expose an unfenced replacement path in the public CLI."""
        parser = execution_cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "create",
                    "--wu",
                    "WU-SAFE",
                    "--objective",
                    "replacement",
                    "--acceptance-criterion",
                    "AC1=must remain fenced",
                    "--replace",
                ]
            )

    def test_create_refuses_to_overwrite_existing_state(self) -> None:
        """Preserve the active RunContext instead of replacing it."""
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            existing = RunContext.new(
                "WU-SAFE",
                "original objective",
                {"AC1": "preserve active state"},
                ResourceBudget(),
                run_id="run-original",
            )
            store.persist_event(existing, "created")

            args = Namespace(
                runtime_root=directory,
                wu="WU-SAFE",
                objective="replacement objective",
                acceptance_criterion=[("AC1", "replacement")],
                max_tokens=None,
                max_active_seconds=None,
                max_errors=3,
                max_unchanged=3,
                run_id="run-replacement",
            )
            with self.assertRaises(FileExistsError):
                execution_cli.cmd_create(args)

            preserved = store.load("WU-SAFE")
            self.assertEqual(preserved.key.run_id, "run-original")
            self.assertEqual(preserved.objective, "original objective")


if __name__ == "__main__":
    unittest.main()
