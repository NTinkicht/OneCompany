from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import qualification  # noqa: E402
import qualification_executor  # noqa: E402
from onecompany_lib import CONTROL, load_json  # noqa: E402


class QualificationExecutorTests(unittest.TestCase):
    def _configs(self):
        return (
            copy.deepcopy(load_json(CONTROL / "actors.json")),
            copy.deepcopy(load_json(CONTROL / "readiness.json")),
            copy.deepcopy(load_json(CONTROL / "dispatch.json")),
            copy.deepcopy(load_json(CONTROL / "budget.json")),
        )

    def test_verified_local_binding_is_read_only_zero_spend_and_advisory(self):
        binding = qualification_executor.validate_binding()
        self.assertEqual(binding["actor"], "onecompany-local")
        self.assertEqual(binding["mechanism"], "onecompany-actions-readonly")
        self.assertEqual(binding["cost_class"], "FREE_ALLOWANCE")
        self.assertEqual(binding["repository_access"], "read_only")
        self.assertFalse(binding["production_write_authority"])
        self.assertEqual(binding["authority"], "advisory_only")
        self.assertEqual(binding["authority_effects"], [])

    def test_all_canonical_scenarios_execute_with_degradation_turns(self):
        exit_code, bundle = qualification_executor.execute_all()
        self.assertEqual(exit_code, 0)
        self.assertEqual(bundle["summary"]["scenario_count"], 8)
        self.assertEqual(bundle["summary"]["passed"], 8)
        self.assertEqual(bundle["summary"]["failed"], 0)
        turns = {run["scenario_id"]: run["turns_executed"] for run in bundle["runs"]}
        self.assertEqual(turns["Q-DUPLICATE-001"], 6)
        self.assertEqual(turns["Q-CAPABILITY-001"], 10)
        for run in bundle["runs"]:
            provenance = run["provenance"]
            self.assertEqual(provenance["authority"], "advisory_only")
            self.assertEqual(provenance["authority_effects"], [])
            self.assertEqual(provenance["executor"]["actor"], "onecompany-local")
            self.assertEqual(
                provenance["executor"]["model_label"],
                "deterministic-policy-probe-v1",
            )

    def test_turn_six_drift_is_detected(self):
        scenario = qualification._scenario_by_id("Q-DUPLICATE-001")

        def drifting_provider(current, turn):
            decisions = list(current["required_decisions"])
            if turn == 6:
                return ["create_duplicate_wu_branch"], decisions
            return [], decisions

        run = qualification_executor.execute_scenario(
            str(scenario["id"]), decision_provider=drifting_provider
        )
        self.assertEqual(run["turns_executed"], 6)
        self.assertEqual(run["exit_code"], 1)
        self.assertIn(
            "forbidden_action:create_duplicate_wu_branch",
            run["provenance"]["result"]["failures"],
        )

    def test_executor_unavailability_fails_closed(self):
        actors, readiness, dispatch, budget = self._configs()
        local = next(item for item in readiness["actors"] if item["actor_id"] == "onecompany-local")
        local["setup_state"] = "blocked"
        with self.assertRaisesRegex(
            qualification_executor.QualificationExecutorError,
            "executor_not_ready",
        ):
            qualification_executor.validate_binding(
                actors=actors,
                readiness=readiness,
                dispatch=dispatch,
                budget=budget,
            )

    def test_unsupported_capability_expansion_fails_closed(self):
        with self.assertRaisesRegex(
            qualification_executor.QualificationExecutorError,
            "unsupported_capability:implementation",
        ):
            qualification_executor.validate_binding(capability="implementation")

    def test_actor_write_permission_expansion_fails_closed(self):
        actors, readiness, dispatch, budget = self._configs()
        local = next(item for item in actors["actors"] if item["id"] == "onecompany-local")
        local["permissions"].append("write_if_connected")
        with self.assertRaisesRegex(
            qualification_executor.QualificationExecutorError,
            "executor_permissions_not_read_only",
        ):
            qualification_executor.validate_binding(
                actors=actors,
                readiness=readiness,
                dispatch=dispatch,
                budget=budget,
            )

    def test_unverified_unattended_state_fails_closed(self):
        actors, readiness, dispatch, budget = self._configs()
        local = next(item for item in readiness["actors"] if item["actor_id"] == "onecompany-local")
        local["unattended"]["verified"] = False
        with self.assertRaisesRegex(
            qualification_executor.QualificationExecutorError,
            "unattended_execution_not_verified",
        ):
            qualification_executor.validate_binding(
                actors=actors,
                readiness=readiness,
                dispatch=dispatch,
                budget=budget,
            )

    def test_paid_fallback_policy_change_fails_closed(self):
        actors, readiness, dispatch, budget = self._configs()
        budget["ai"]["allow_paid_fallback"] = True
        with self.assertRaisesRegex(
            qualification_executor.QualificationExecutorError,
            "zero_spend_policy:allow_paid_fallback",
        ):
            qualification_executor.validate_binding(
                actors=actors,
                readiness=readiness,
                dispatch=dispatch,
                budget=budget,
            )

    def test_mechanism_capability_drift_fails_closed(self):
        actors, readiness, dispatch, budget = self._configs()
        local = next(item for item in dispatch["actors"] if item["actor_id"] == "onecompany-local")
        local["mechanisms"][0]["capabilities"] = []
        with self.assertRaisesRegex(
            qualification_executor.QualificationExecutorError,
            "mechanism_capability_not_registered",
        ):
            qualification_executor.validate_binding(
                actors=actors,
                readiness=readiness,
                dispatch=dispatch,
                budget=budget,
            )

    def test_execution_does_not_mutate_control_plane(self):
        paths = [
            CONTROL / "actors.json",
            CONTROL / "readiness.json",
            CONTROL / "dispatch.json",
            CONTROL / "budget.json",
            CONTROL / "ledger.json",
        ]
        before = {path: path.read_bytes() for path in paths}
        exit_code, bundle = qualification_executor.execute_all()
        after = {path: path.read_bytes() for path in paths}
        self.assertEqual(exit_code, 0)
        self.assertEqual(before, after)
        self.assertEqual(bundle["authority_effects"], [])
        self.assertFalse(bundle["binding"]["production_write_authority"])


if __name__ == "__main__":
    unittest.main()
