"""Intake reports partial GitHub mutations separately from read-only blocks."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import mistral_cloud_start as start


class MistralIntakeReconcileTests(unittest.TestCase):
    def test_preflight_refusal_is_prewrite_and_never_starts(self):
        stdout = io.StringIO()
        with patch.object(start, "prepare", side_effect=ValueError("secret")):
            with patch.object(start, "start") as run:
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(start.main(), 2)
                run.assert_not_called()
        self.assertEqual(json.loads(stdout.getvalue()), {
            "status": "START_BLOCKED_PREWRITE",
        })
        self.assertNotIn("secret", stdout.getvalue())

    def test_mutation_uncertainty_requires_reconcile_not_retry(self):
        ticket = {
            "work_unit": "WU-CLOUD-MISTRAL-DEV-001",
            "branch": "wu-cloud-mistral-dev-001",
            "main_sha": "a" * 40,
        }
        stdout = io.StringIO()
        with patch.object(start, "prepare", return_value=ticket):
            with patch.object(start, "start",
                              side_effect=ValueError("private GitHub response")) as run:
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(start.main(), 2)
                run.assert_called_once_with(ticket)
        self.assertEqual(json.loads(stdout.getvalue()), {
            "status": "START_RECONCILE_REQUIRED",
            **ticket,
        })
        self.assertNotIn("private", stdout.getvalue())

    def test_success_has_actual_pr_identity_not_generic_prepared(self):
        ticket = {
            "work_unit": "WU-CLOUD-MISTRAL-DEV-001",
            "branch": "wu-cloud-mistral-dev-001",
            "main_sha": "a" * 40,
        }
        output = {
            "status": "CANONICAL_DRAFT_PR_AWAITING_QUEUE_BINDING_AND_LEASE",
            "pr": 224,
            "head": "b" * 40,
        }
        stdout = io.StringIO()
        with patch.object(start, "prepare", return_value=ticket):
            with patch.object(start, "start", return_value=output):
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(start.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue()), output)

    def test_wake_bus_reports_reconcile_after_nonzero(self):
        workflow = (ROOT / ".github/workflows/onecompany-mistral-start.yml").read_text()
        self.assertIn("if [[ -s /tmp/mistral-start-result.json ]]; then", workflow)
        self.assertIn("cat /tmp/mistral-start-result.json", workflow)
        self.assertIn("START_BLOCKED_OR_RECONCILE_REQUIRED", workflow)
        self.assertIn("persist-credentials: false", workflow)


if __name__ == "__main__":
    unittest.main()
