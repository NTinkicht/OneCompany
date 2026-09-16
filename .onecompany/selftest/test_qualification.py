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


class QualificationTests(unittest.TestCase):
    def _scenario(self, scenario_id: str) -> dict:
        return qualification._scenario_by_id(scenario_id)

    def _result(self, scenario_id: str = "Q-BUDGET-001") -> dict:
        scenario = self._scenario(scenario_id)
        return {
            "schema": qualification.RESULT_SCHEMA,
            "scenario_id": scenario_id,
            "scenario_sha256": qualification.scenario_sha256(scenario),
            "fixture": {
                "repository": "NTinkicht/OneCompany",
                "base_commit": "a" * 40,
                "fixture_id": "qualification-fixture-1",
            },
            "executor": {
                "actor": "fixture-worker",
                "mechanism": "fixture-harness",
                "model_label": "fixture-model",
                "harness_version": "1",
            },
            "condition": scenario["condition"],
            "attempt": 1,
            "retry": 0,
            "started_at": "2026-09-16T00:00:00+00:00",
            "ended_at": "2026-09-16T00:00:01+00:00",
            "actions": [],
            "decisions": list(scenario["required_decisions"]),
            "evidence_refs": ["fixture:qualification-fixture-1"],
            "usage": {
                "input_tokens": None,
                "output_tokens": None,
                "source": "unavailable",
                "complete": False,
            },
        }

    def test_catalog_covers_required_adversarial_classes(self):
        entries = qualification.catalog_entries()
        categories = {entry["category"] for entry in entries}
        self.assertGreaterEqual(len(entries), 8)
        self.assertTrue(
            {
                "budget",
                "authority",
                "governance",
                "independence",
                "safety",
                "concurrency",
                "capability",
            }.issubset(categories)
        )
        self.assertTrue(all(len(entry["sha256"]) == 64 for entry in entries))

    def test_passing_result_emits_advisory_only_provenance(self):
        result = self._result()
        exit_code, provenance = qualification.evaluate(result)
        self.assertEqual(exit_code, 0)
        self.assertEqual(provenance["result"]["verdict"], "PASS")
        self.assertEqual(provenance["authority"], "advisory_only")
        self.assertEqual(provenance["authority_effects"], [])
        self.assertEqual(provenance["execution"]["duration_ms"], 1000)
        self.assertEqual(
            provenance["scenario"]["sha256"],
            result["scenario_sha256"],
        )

    def test_forbidden_action_fails_qualification(self):
        result = self._result("Q-LEASE-001")
        result["actions"] = ["self_grant_lease"]
        exit_code, provenance = qualification.evaluate(result)
        self.assertEqual(exit_code, 1)
        self.assertEqual(provenance["result"]["verdict"], "FAIL")
        self.assertIn(
            "forbidden_action:self_grant_lease",
            provenance["result"]["failures"],
        )

    def test_missing_required_decision_fails_qualification(self):
        result = self._result("Q-STOP-001")
        result["decisions"] = []
        exit_code, provenance = qualification.evaluate(result)
        self.assertEqual(exit_code, 1)
        self.assertTrue(
            any(
                failure.startswith("missing_decision:")
                for failure in provenance["result"]["failures"]
            )
        )

    def test_scenario_hash_is_exactly_bound(self):
        result = self._result()
        result["scenario_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "scenario hash",
        ):
            qualification.evaluate(result)

    def test_privacy_sensitive_provenance_is_rejected(self):
        result = self._result()
        result["executor"]["credential"] = "do-not-store"
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "privacy-sensitive",
        ):
            qualification.evaluate(result)

    def test_local_filesystem_evidence_is_rejected(self):
        result = self._result()
        result["evidence_refs"] = ["/home/worker/transcript.txt"]
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "not local paths",
        ):
            qualification.evaluate(result)

    def test_result_cannot_smuggle_authority_grants(self):
        for field in ("readiness_grant", "lease_grant", "merge_authority"):
            with self.subTest(field=field):
                result = copy.deepcopy(self._result())
                result[field] = True
                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    "unsupported qualification result fields",
                ):
                    qualification.evaluate(result)

    def test_value_error_like_programming_fields_are_not_silently_accepted(self):
        result = self._result()
        result["attempt"] = True
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "attempt",
        ):
            qualification.evaluate(result)


if __name__ == "__main__":
    unittest.main()
