from __future__ import annotations

import contextlib
import copy
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import bootstrap  # noqa: E402
import knowledge_validate  # noqa: E402
import planner  # noqa: E402
import qualification  # noqa: E402
import qualification_executor  # noqa: E402


class IntegrationPromotionRemediationTests(unittest.TestCase):
    def _work_item(self) -> dict:
        return {
            "id": "WU-TEST-REMEDIATION",
            "title": "Exercise advisory knowledge degradation",
            "work_kind": "ENABLER",
            "risk_class": "HIGH",
            "planning_refs": ["CAP-AUTHORITY"],
            "write_scope": ["scripts/planner.py"],
        }

    def test_planner_keeps_stable_advisory_schema_on_qualification_input_error(self):
        with mock.patch.object(
            planner.knowledge,
            "preflight",
            side_effect=qualification.QualificationInputError("malformed knowledge"),
        ):
            value = planner.learning_preflight(self._work_item())

        self.assertEqual(value["schema"], "onecompany-learning-preflight-v1")
        self.assertEqual(value["authority"], "advisory_only")
        self.assertEqual(value["authority_effects"], [])
        self.assertFalse(value["hard_gate_created"])
        self.assertEqual(value["questions"], [])
        self.assertEqual(value["lesson_ids"], [])
        self.assertEqual(value["checks"], [])
        self.assertEqual(value["regression_tests"], [])
        self.assertIn("malformed knowledge", value["diagnostic"])

    def test_knowledge_validator_normalizes_qualification_input_error(self):
        output = io.StringIO()
        with mock.patch.object(
            knowledge_validate.knowledge,
            "load_entries",
            side_effect=qualification.QualificationInputError("bad provenance"),
        ), contextlib.redirect_stdout(output):
            exit_code = knowledge_validate.main()

        self.assertEqual(exit_code, 1)
        self.assertIn("KNOWLEDGE INVALID: bad provenance", output.getvalue())

    def test_public_qualification_execution_rejects_supplied_stale_binding(self):
        binding = qualification_executor.validate_binding()
        stale = copy.deepcopy(binding)
        stale["actor"] = "chatgpt"
        with self.assertRaisesRegex(
            qualification_executor.QualificationExecutorError,
            "supplied_binding_stale_or_untrusted",
        ):
            qualification_executor.execute_scenario(
                "Q-BUDGET-001",
                binding=stale,
            )

    def test_intermediate_decision_drift_cannot_be_erased_by_later_recovery(self):
        scenario = qualification._scenario_by_id("Q-CAPABILITY-001")

        def drifting_provider(current, turn):
            decisions = list(current["required_decisions"])
            if turn == 6:
                return [], ["unsafe_capability_expansion"]
            return [], decisions

        run = qualification_executor.execute_scenario(
            str(scenario["id"]),
            decision_provider=drifting_provider,
        )

        self.assertEqual(run["turns_executed"], 10)
        self.assertEqual(run["exit_code"], 1)
        self.assertTrue(run["provenance"]["result"]["failures"])

    @unittest.skipUnless(
        getattr(os, "O_NOFOLLOW", 0) and getattr(os, "O_DIRECTORY", 0),
        "descriptor-bound no-follow cleanup requires POSIX directory flags",
    )
    def test_bootstrap_refuses_symlinked_knowledge_state_without_external_delete(self):
        with tempfile.TemporaryDirectory() as target_dir, tempfile.TemporaryDirectory() as outside_dir:
            target = Path(target_dir)
            root = target / ".onecompany" / "knowledge"
            root.mkdir(parents=True)
            outside = Path(outside_dir)
            victim = outside / "victim.json"
            victim.write_text('{"keep": true}\n', encoding="utf-8")
            (root / "candidate").symlink_to(outside, target_is_directory=True)
            (root / "current").mkdir()

            with self.assertRaises(ValueError):
                bootstrap.initialize_knowledge(target)

            self.assertTrue(victim.exists())
            self.assertEqual(victim.read_text(encoding="utf-8"), '{"keep": true}\n')


if __name__ == "__main__":
    unittest.main()
