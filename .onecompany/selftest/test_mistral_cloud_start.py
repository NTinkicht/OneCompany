"""Offline tests: draft PR intake cannot silently mint implementation authority."""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import mistral_cloud_start as start

SHA = "a" * 40
COMMAND = f"@mistral-vibe\nMISTRAL_START_V1\nwork_unit: WU-CLOUD-MISTRAL-DEV-001\nmain_sha: {SHA}"


class MistralCanonicalIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = json.loads((ROOT / ".onecompany/queue.json").read_text())
        cls.budget = json.loads((ROOT / ".onecompany/budget.json").read_text())
        cls.config = json.loads((ROOT / ".onecompany/config.json").read_text())

    def ticket(self, *, queue=None, budget=None, config=None, sha=SHA):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": start.REPO,
                                      "ONECOMPANY_EMERGENCY_STOP": "false"}):
            return start.policy_ticket(
                start.assignment(COMMAND),
                queue=queue or self.queue,
                budget=budget or self.budget,
                config=config or self.config,
                actual_main_sha=sha,
            )

    def test_ready_low_risk_predeclared_scope_and_draft_only(self):
        w = self.ticket()
        self.assertEqual(w["work_unit"], "WU-CLOUD-MISTRAL-DEV-001")
        self.assertEqual(w["branch"], "wu-cloud-mistral-dev-001")
        self.assertIn("tests/test_agent_qualification.py", w["scope"])
        self.assertEqual(w["test_path"], "tests/test_agent_qualification.py")
        workflow = (ROOT / ".github/workflows/onecompany-mistral-start.yml").read_text()
        self.assertIn("github.actor == 'NTinkicht'", workflow)
        self.assertIn("github.event.issue.number == 130", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertIn("PR_PREPARED_NOT_MODEL_QUALIFIED", workflow)

    def test_strict_owner_assignment_cannot_inject_other_scope(self):
        for body in (
            COMMAND + "\nbranch: main",
            COMMAND.replace("MISTRAL_START_V1", "MISTRAL_START_V1 EXTRA"),
            COMMAND.replace("main_sha: " + SHA, "main_sha: main"),
            COMMAND.replace("WU-CLOUD-MISTRAL-DEV-001", "WU-OTHER"),
            COMMAND + "\nMISTRAL_START_V1",
        ):
            with self.subTest(body=body[:70]), self.assertRaises(ValueError):
                start.assignment(body)

    def test_no_lease_or_code_qualification_from_branch_scaffold(self):
        code = (ROOT / "scripts/mistral_cloud_start.py").read_text()
        self.assertIn("NOT model-authored code", code)
        self.assertIn("A reviewed protected-main WU PR-number", code)
        self.assertNotIn("ROLE_LEASE_ASSIGNED", code)
        self.assertNotIn("Material-Author: mistral-vibe", code)

    def test_stale_unknown_ready_risk_and_duplicate_branch_fail(self):
        with self.assertRaisesRegex(ValueError, "MAIN_STALE"):
            self.ticket(sha="b" * 40)
        for name, value in (
            ("status", "PROPOSED"), ("risk_class", "HIGH"),
            ("pr", 123), ("branch", "main"),
        ):
            q = copy.deepcopy(self.queue)
            row = next(w for w in q["work_units"]
                       if w["id"] == "WU-CLOUD-MISTRAL-DEV-001")
            row[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.ticket(queue=q)
        q = copy.deepcopy(self.queue)
        q["work_units"].append(
            {"id": "WU-OTHER", "branch": "wu-cloud-mistral-dev-001"}
        )
        with self.assertRaisesRegex(ValueError, "BRANCH_CONFLICT"):
            self.ticket(queue=q)

    def test_no_paid_fallback_and_emergency_stop(self):
        for field, value in (
            ("allow_paid_fallback", True), ("allow_overage", True),
            ("allow_auto_topup", True), ("allow_new_paid_vendor", True),
            ("additional_monthly_spend_cap", 1),
            ("unknown_cost_behavior", "allow"),
        ):
            budget = copy.deepcopy(self.budget)
            budget["ai"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "FINANCIAL_POLICY_BLOCKED"
            ):
                self.ticket(budget=budget)
        config = copy.deepcopy(self.config)
        config["safety"]["emergency_stop"] = True
        with self.assertRaisesRegex(ValueError, "EMERGENCY_STOP"):
            self.ticket(config=config)


if __name__ == "__main__":
    unittest.main()
