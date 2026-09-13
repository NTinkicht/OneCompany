from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trusted_assurance

CANDIDATE = "a" * 40
BASE = "b" * 40


class TrustedAssuranceTests(unittest.TestCase):
    def packet(self, run_id: int = 101) -> dict:
        return {
            "work_unit": "WU-KERNEL-003",
            "candidate_sha": CANDIDATE,
            "quality_profile": "production",
            "risk_level": "low",
            "code_change": True,
            "material_authors": ["chatgpt"],
            "evidence": {
                "references": [
                    {
                        "id": "EVID-001",
                        "provider": "github_actions",
                        "source_kind": "artifact",
                        "workflow_run_id": run_id,
                        "artifact_id": 202,
                        "artifact_name": "quality-evidence",
                        "parser": {
                            "kind": "onecompany_quality_json_v1",
                            "version": 1,
                            "path": "quality.json",
                        },
                    }
                ],
                "review_reference": {"review_id": 303},
                # Deliberately forged legacy claims: trusted_assurance must ignore them.
                "coverage": {"line": 100, "branch": 100, "changed_line": 100, "mutation": 100},
                "test_family_results": {"static": "pass", "unit": "pass", "regression": "pass"},
            },
        }

    def quality(self) -> dict:
        return {
            "profile": "production",
            "profiles": {
                "production": {
                    "line_coverage_min": 85,
                    "branch_coverage_min": 80,
                    "changed_line_coverage_min": 95,
                    "mutation_score_min": 70,
                }
            },
            "risk_required_families": {"low": ["static", "unit", "regression"]},
        }

    def required_checks(self) -> list[dict]:
        return [
            {
                "name": "validate",
                "id": 777,
                "workflow_run_id": 101,
                "workflow_path": ".github/workflows/onecompany-validate.yml",
                "trusted_ref": BASE,
                "trusted_workflow_blob_sha": "c" * 40,
                "status": "completed",
                "conclusion": "success",
                "head_sha": CANDIDATE,
            }
        ]

    def workflow(self) -> dict:
        return {
            "id": 101,
            "path": ".github/workflows/onecompany-validate.yml",
            "head_sha": CANDIDATE,
            "status": "completed",
            "conclusion": "success",
            "pull_requests": [
                {
                    "number": 11,
                    "head": {"sha": CANDIDATE},
                    "base": {"sha": BASE},
                }
            ],
        }

    def verified_artifact(self, mutation: float = 75) -> dict:
        return {
            "id": "EVID-001",
            "verified": True,
            "workflow": {"id": 101, "path": ".github/workflows/onecompany-validate.yml"},
            "artifact": {
                "id": 202,
                "name": "quality-evidence",
                "digest_sha256": "d" * 64,
            },
            "parser": {"kind": "onecompany_quality_json_v1", "version": 1, "path": "quality.json"},
            "extracted": {
                "coverage": {"line": 92, "branch": 86, "changed_line": 98, "mutation": mutation},
                "test_families": {"static": "pass", "unit": "pass", "regression": "pass"},
            },
            "errors": [],
        }

    def review(self) -> dict:
        return {
            "verified": True,
            "review_id": 303,
            "state": "APPROVED",
            "commit_id": CANDIDATE,
            "reviewer_login": "independent-reviewer",
            "submitted_at": "2026-01-01T00:00:00Z",
            "errors": [],
        }

    def common_patches(self, *, artifact=None):
        artifact = artifact or self.verified_artifact()
        return (
            patch.object(trusted_assurance.evidence_verify, "verify_pr_context", return_value=({"head_sha": CANDIDATE, "base_sha": BASE}, None)),
            patch.object(trusted_assurance, "_base_json", side_effect=[(self.quality(), "q" * 40, None), ({"checks": []}, "r" * 40, None)]),
            patch.object(trusted_assurance, "evaluate_required_checks", return_value=(True, [], self.required_checks())),
            patch.object(trusted_assurance.evidence_verify, "_workflow_run", return_value=(self.workflow(), None)),
            patch.object(trusted_assurance.evidence_verify, "verify_artifact_reference", return_value=artifact),
            patch.object(trusted_assurance.evidence_verify, "verify_review_reference", return_value=self.review()),
        )

    def test_artifact_must_come_from_base_trusted_required_check_run(self):
        packet = self.packet(run_id=999)
        patches = self.common_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4] as artifact_verify, patches[5]:
            attestation, errors = trusted_assurance.verify_trusted_packet(packet, repo="owner/repo", pr=11, base_sha=BASE)
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(any("not a base-trusted required-check run" in error for error in errors), errors)
        artifact_verify.assert_not_called()

    def test_forged_packet_numbers_cannot_override_extracted_failure(self):
        packet = self.packet()
        patches = self.common_patches(artifact=self.verified_artifact(mutation=40))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            attestation, errors = trusted_assurance.verify_trusted_packet(packet, repo="owner/repo", pr=11, base_sha=BASE)
        self.assertEqual(packet["evidence"]["coverage"]["mutation"], 100)
        self.assertEqual(attestation["extracted"]["coverage"]["mutation"], 40.0)
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(any("mutation=40" in error for error in errors), errors)

    def test_pass_attestation_records_check_artifact_and_base_policy_identity(self):
        packet = self.packet()
        patches = self.common_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            attestation, errors = trusted_assurance.verify_trusted_packet(packet, repo="owner/repo", pr=11, base_sha=BASE)
        self.assertEqual(errors, [])
        self.assertEqual(attestation["verdict"], "PASS")
        self.assertEqual(attestation["head_sha"], CANDIDATE)
        self.assertEqual(attestation["base_sha"], BASE)
        self.assertEqual(attestation["required_checks"][0]["workflow_run_id"], 101)
        self.assertEqual(attestation["artifacts"][0]["artifact_id"], 202)
        self.assertEqual(attestation["artifacts"][0]["digest_sha256"], "d" * 64)
        self.assertIn("quality:" + "q" * 40, attestation["policy_revision"])
        self.assertIn("required-checks:" + "r" * 40, attestation["policy_revision"])
        self.assertIn("generated_at", attestation)

    def test_lower_packet_profile_cannot_undercut_base_policy(self):
        packet = self.packet()
        packet["quality_profile"] = "prototype"
        quality = self.quality()
        quality["profiles"]["prototype"] = {
            "line_coverage_min": 0,
            "branch_coverage_min": 0,
            "changed_line_coverage_min": 0,
            "mutation_score_min": 0,
        }
        patches = self.common_patches()
        with (
            patches[0],
            patch.object(trusted_assurance, "_base_json", side_effect=[(quality, "q" * 40, None), ({"checks": []}, "r" * 40, None)]),
            patches[2], patches[3], patches[4], patches[5],
        ):
            attestation, errors = trusted_assurance.verify_trusted_packet(packet, repo="owner/repo", pr=11, base_sha=BASE)
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(any("below base-trusted minimum" in error for error in errors), errors)

    def test_workflow_must_bind_exact_pr_head_and_base(self):
        packet = self.packet()
        wrong = self.workflow()
        wrong["pull_requests"][0]["base"]["sha"] = "e" * 40
        patches = self.common_patches()
        with patches[0], patches[1], patches[2], patch.object(trusted_assurance.evidence_verify, "_workflow_run", return_value=(wrong, None)), patches[4] as artifact_verify, patches[5]:
            attestation, errors = trusted_assurance.verify_trusted_packet(packet, repo="owner/repo", pr=11, base_sha=BASE)
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(any("exact PR/head/base" in error for error in errors), errors)
        artifact_verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
