from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import qualification  # noqa: E402


class QualificationTests(unittest.TestCase):
    def _scenario(self, scenario_id: str) -> dict:
        return qualification._scenario_by_id(scenario_id)

    def _fixture(self, scenario: dict) -> dict:
        return qualification._fixture_by_id(str(scenario["fixture_id"]))

    def _result(self, scenario_id: str = "Q-BUDGET-001") -> dict:
        scenario = self._scenario(scenario_id)
        fixture = self._fixture(scenario)
        return {
            "schema": qualification.RESULT_SCHEMA,
            "scenario_id": scenario_id,
            "scenario_sha256": qualification.scenario_sha256(scenario),
            "fixture": {
                "repository": fixture["repository"],
                "base_commit": fixture["base_commit"],
                "fixture_id": fixture["id"],
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
            "evidence_refs": list(scenario["required_evidence_refs"]),
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
        self.assertTrue(all(entry["fixture_id"] == "onecompany-qualification-v1" for entry in entries))

    def test_passing_result_emits_advisory_only_provenance(self):
        result = self._result()
        exit_code, provenance = qualification.evaluate(result)
        self.assertEqual(exit_code, 0)
        self.assertEqual(provenance["result"]["verdict"], "PASS")
        self.assertEqual(provenance["authority"], "advisory_only")
        self.assertEqual(provenance["authority_effects"], [])
        self.assertEqual(provenance["execution"]["duration_ms"], 1000)
        self.assertEqual(provenance["fixture"], result["fixture"])
        self.assertEqual(provenance["evidence_refs"], result["evidence_refs"])
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

    def test_actions_and_decisions_must_be_catalog_backed_labels(self):
        result = self._result()
        result["actions"] = ["unregistered_action"]
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "outside the canonical scenario catalog",
        ):
            qualification.evaluate(result)

        result = self._result()
        result["decisions"].append("unregistered_decision")
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "outside the canonical scenario catalog",
        ):
            qualification.evaluate(result)

    def test_scenario_hash_is_exactly_bound(self):
        result = self._result()
        result["scenario_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "scenario hash",
        ):
            qualification.evaluate(result)

    def test_fixture_repository_commit_and_id_are_exactly_bound(self):
        mutations = (
            ("repository", "attacker/other"),
            ("base_commit", "f" * 40),
            ("fixture_id", "other-fixture"),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                result = self._result()
                result["fixture"][key] = value
                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    "canonical scenario fixture|canonical fixture catalog",
                ):
                    qualification.evaluate(result)

    def test_evidence_refs_are_exactly_bound_to_scenario_fixture(self):
        result = self._result()
        result["evidence_refs"] = list(result["evidence_refs"])
        result["evidence_refs"][0] = "fixture:onecompany-qualification-v1/Q-LEASE-001"
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "canonical scenario fixture contract",
        ):
            qualification.evaluate(result)

        result = self._result()
        result["evidence_refs"] = list(reversed(result["evidence_refs"]))
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "canonical scenario fixture contract",
        ):
            qualification.evaluate(result)

        result = self._result()
        result["evidence_refs"].append("https://example.com/extra")
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "canonical scenario fixture contract",
        ):
            qualification.evaluate(result)

    def test_privacy_sensitive_provenance_key_is_rejected(self):
        result = self._result()
        result["executor"]["credential"] = "do-not-store"
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "privacy-sensitive provenance field",
        ):
            qualification.evaluate(result)

    def test_privacy_sensitive_provenance_value_is_rejected(self):
        result = self._result()
        result["executor"]["actor"] = "github_pat_abcdefghijklmnopqrstuvwxyz123456"
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "privacy-sensitive provenance value",
        ):
            qualification.evaluate(result)

    def test_executor_fields_are_normalized_identifiers(self):
        result = self._result()
        result["executor"]["model_label"] = "fixture model with spaces"
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "normalized identifier",
        ):
            qualification.evaluate(result)

    def test_local_filesystem_evidence_is_rejected(self):
        with self.assertRaisesRegex(
            qualification.QualificationInputError,
            "not local paths",
        ):
            qualification._validate_evidence_ref("/home/worker/transcript.txt")

    def test_https_evidence_rejects_credentials_secret_queries_and_fragments(self):
        cases = (
            ("https://user@example.com/evidence", "user information"),
            ("https://example.com/evidence?auth=abc", "secret-like query"),
            ("https://example.com/evidence#private", "fragment"),
            ("https:///missing-host", "malformed host"),
        )
        for ref, message in cases:
            with self.subTest(ref=ref):
                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    message,
                ):
                    qualification._validate_evidence_ref(ref)

    def test_safe_https_evidence_is_structurally_accepted(self):
        qualification._validate_evidence_ref(
            "https://github.com/NTinkicht/OneCompany/actions/runs/123?attempt=1"
        )

    def test_output_is_confined_and_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            artifact_root = repo_root / ".onecompany-evidence" / "qualification"
            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
            ):
                unsafe = repo_root / ".onecompany" / "config.json"
                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    "must remain under",
                ):
                    qualification._write_or_print({"safe": True}, unsafe)

                target = artifact_root / "result.json"
                qualification._write_or_print({"safe": True}, target)
                self.assertTrue(target.exists())

                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    "already exists",
                ):
                    qualification._write_or_print({"safe": False}, target)

                qualification._write_or_print(
                    {"safe": False},
                    target,
                    overwrite=True,
                )
                self.assertIn("false", target.read_text(encoding="utf-8"))

    def test_overwrite_rejects_final_output_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            control = repo_root / ".onecompany" / "config.json"
            control.parent.mkdir(parents=True)
            control.write_text("protected\n", encoding="utf-8")
            artifact_root = repo_root / ".onecompany-evidence" / "qualification"
            artifact_root.mkdir(parents=True)
            target = artifact_root / "result.json"
            target.symlink_to(control)
            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
            ):
                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    "must not be a symlink|must remain under",
                ):
                    qualification._write_or_print(
                        {"safe": False},
                        target,
                        overwrite=True,
                    )
            self.assertEqual(control.read_text(encoding="utf-8"), "protected\n")

    def test_symlinked_artifact_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            control_dir = repo_root / ".onecompany"
            control_dir.mkdir(parents=True)
            protected = control_dir / "config.json"
            protected.write_text("protected\n", encoding="utf-8")
            evidence_parent = repo_root / ".onecompany-evidence"
            evidence_parent.mkdir()
            artifact_root = evidence_parent / "qualification"
            artifact_root.symlink_to(control_dir, target_is_directory=True)
            target = artifact_root / "config.json"
            with (
                patch.object(qualification, "ROOT", repo_root),
                patch.object(qualification, "OUTPUT_ROOT", artifact_root),
            ):
                with self.assertRaisesRegex(
                    qualification.QualificationInputError,
                    "symlink components",
                ):
                    qualification._write_or_print(
                        {"safe": False},
                        target,
                        overwrite=True,
                    )
            self.assertEqual(protected.read_text(encoding="utf-8"), "protected\n")

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
