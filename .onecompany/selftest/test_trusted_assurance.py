from __future__ import annotations

import math
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
            "status": "merge_ready",
            "work_unit": "WU-KERNEL-003",
            "candidate_sha": CANDIDATE,
            "quality_profile": "production",
            "risk_level": "high",
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
                # Deliberately forged compatibility claims: never decision inputs.
                "coverage": {
                    "line": 100,
                    "branch": 100,
                    "changed_line": 100,
                    "mutation": 100,
                },
                "test_family_results": {
                    "static": "pass",
                    "unit": "pass",
                    "regression": "pass",
                },
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
            "risk_required_families": {
                "low": ["static", "unit", "regression"],
                "medium": ["static", "unit", "regression"],
                "high": ["static", "unit", "regression"],
            },
        }

    def governance(self) -> dict:
        return {
            "control_plane": {
                "protected_paths": [".onecompany/**", "scripts/**", ".github/**", "onecompany.py"]
            }
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
            "workflow": {
                "id": 101,
                "path": ".github/workflows/onecompany-validate.yml",
            },
            "artifact": {
                "id": 202,
                "name": "quality-evidence",
                "digest_sha256": "d" * 64,
            },
            "parser": {
                "kind": "onecompany_quality_json_v1",
                "version": 1,
                "path": "quality.json",
            },
            "extracted": {
                "coverage": {
                    "line": 92,
                    "branch": 86,
                    "changed_line": 98,
                    "mutation": mutation,
                },
                "test_families": {
                    "static": "pass",
                    "unit": "pass",
                    "regression": "pass",
                },
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

    def common_patches(self, *, artifact=None, changed_files=None):
        artifact = artifact or self.verified_artifact()
        changed_files = changed_files or ["scripts/trusted_assurance.py"]
        return (
            patch.object(
                trusted_assurance.evidence_verify,
                "verify_pr_context",
                return_value=({"head_sha": CANDIDATE, "base_sha": BASE}, None),
            ),
            patch.object(
                trusted_assurance,
                "_live_changed_paths",
                return_value=(changed_files, None),
            ),
            patch.object(
                trusted_assurance,
                "_base_json",
                side_effect=[
                    (self.quality(), "q" * 40, None),
                    ({"checks": []}, "r" * 40, None),
                    (self.governance(), "g" * 40, None),
                ],
            ),
            patch.object(
                trusted_assurance,
                "evaluate_required_checks",
                return_value=(True, [], self.required_checks()),
            ),
            patch.object(
                trusted_assurance.evidence_verify,
                "_workflow_run",
                return_value=(self.workflow(), None),
            ),
            patch.object(
                trusted_assurance.evidence_verify,
                "verify_artifact_reference",
                return_value=artifact,
            ),
            patch.object(
                trusted_assurance.evidence_verify,
                "verify_review_reference",
                return_value=self.review(),
            ),
        )

    def run_verify(self, packet: dict, *, artifact=None, changed_files=None):
        patches = self.common_patches(artifact=artifact, changed_files=changed_files)
        with (
            patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]
        ):
            return trusted_assurance.verify_trusted_packet(
                packet, repo="owner/repo", pr=11, base_sha=BASE
            )

    def test_artifact_must_come_from_base_trusted_required_check_run(self):
        packet = self.packet(run_id=999)
        patches = self.common_patches()
        with (
            patches[0], patches[1], patches[2], patches[3], patches[4],
            patches[5] as artifact_verify, patches[6]
        ):
            attestation, errors = trusted_assurance.verify_trusted_packet(
                packet, repo="owner/repo", pr=11, base_sha=BASE
            )
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(
            any("not a base-trusted required-check run" in error for error in errors),
            errors,
        )
        artifact_verify.assert_not_called()

    def test_forged_packet_numbers_cannot_override_extracted_failure(self):
        packet = self.packet()
        attestation, errors = self.run_verify(
            packet, artifact=self.verified_artifact(mutation=40)
        )
        self.assertEqual(packet["evidence"]["coverage"]["mutation"], 100)
        self.assertEqual(attestation["extracted"]["coverage"]["mutation"], 40.0)
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(any("mutation=40" in error for error in errors), errors)

    def test_pass_attestation_records_trusted_scope_and_policy_identity(self):
        packet = self.packet()
        attestation, errors = self.run_verify(packet)
        self.assertEqual(errors, [])
        self.assertEqual(attestation["verdict"], "PASS")
        self.assertEqual(attestation["head_sha"], CANDIDATE)
        self.assertEqual(attestation["base_sha"], BASE)
        self.assertTrue(attestation["code_change"])
        self.assertEqual(attestation["risk_level"], "high")
        self.assertEqual(attestation["protected_files"], ["scripts/trusted_assurance.py"])
        self.assertEqual(attestation["required_checks"][0]["workflow_run_id"], 101)
        self.assertEqual(attestation["artifacts"][0]["artifact_id"], 202)
        self.assertEqual(attestation["artifacts"][0]["digest_sha256"], "d" * 64)
        self.assertIn("quality:" + "q" * 40, attestation["policy_revision"])
        self.assertIn("required-checks:" + "r" * 40, attestation["policy_revision"])
        self.assertIn("governance:" + "g" * 40, attestation["policy_revision"])

    def test_packet_cannot_suppress_live_code_change(self):
        packet = self.packet()
        packet["code_change"] = False
        attestation, errors = self.run_verify(packet)
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(any("code_change" in error and "live scope" in error for error in errors), errors)
        self.assertTrue(attestation["code_change"])

    def test_packet_cannot_understate_protected_scope_risk(self):
        packet = self.packet()
        packet["risk_level"] = "low"
        attestation, errors = self.run_verify(packet)
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(any("derived risk 'high'" in error for error in errors), errors)
        self.assertEqual(attestation["risk_level"], "high")

    def test_direct_attestation_rejects_non_merge_lifecycle_or_missing_authors(self):
        packet = self.packet()
        packet["status"] = "draft"
        packet["material_authors"] = []
        attestation, errors = trusted_assurance.verify_trusted_packet(
            packet, repo="owner/repo", pr=11, base_sha=BASE
        )
        self.assertIsNone(attestation)
        self.assertTrue(any("merge_ready or done" in error for error in errors), errors)
        self.assertTrue(any("material_authors" in error for error in errors), errors)

    def test_nonfinite_and_out_of_range_verified_metrics_fail(self):
        packet = self.packet()
        bad = self.verified_artifact()
        bad["extracted"]["coverage"]["line"] = math.nan
        bad["extracted"]["coverage"]["branch"] = 999
        attestation, errors = self.run_verify(packet, artifact=bad)
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(any("not finite" in error for error in errors), errors)
        self.assertTrue(any("outside 0..100" in error for error in errors), errors)

    def test_unsupported_parser_version_never_reaches_artifact_verifier(self):
        packet = self.packet()
        packet["evidence"]["references"][0]["parser"]["version"] = 999
        patches = self.common_patches()
        with (
            patches[0], patches[1], patches[2], patches[3], patches[4],
            patches[5] as artifact_verify, patches[6]
        ):
            attestation, errors = trusted_assurance.verify_trusted_packet(
                packet, repo="owner/repo", pr=11, base_sha=BASE
            )
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(any("unsupported parser version" in error for error in errors), errors)
        artifact_verify.assert_not_called()

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
            patches[1],
            patch.object(
                trusted_assurance,
                "_base_json",
                side_effect=[
                    (quality, "q" * 40, None),
                    ({"checks": []}, "r" * 40, None),
                    (self.governance(), "g" * 40, None),
                ],
            ),
            patches[3], patches[4], patches[5], patches[6],
        ):
            attestation, errors = trusted_assurance.verify_trusted_packet(
                packet, repo="owner/repo", pr=11, base_sha=BASE
            )
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(
            any("below base-trusted minimum" in error for error in errors), errors
        )

    def test_workflow_must_bind_exact_pr_head_and_base(self):
        packet = self.packet()
        wrong = self.workflow()
        wrong["pull_requests"][0]["base"]["sha"] = "e" * 40
        patches = self.common_patches()
        with (
            patches[0], patches[1], patches[2], patches[3],
            patch.object(
                trusted_assurance.evidence_verify,
                "_workflow_run",
                return_value=(wrong, None),
            ),
            patches[5] as artifact_verify,
            patches[6],
        ):
            attestation, errors = trusted_assurance.verify_trusted_packet(
                packet, repo="owner/repo", pr=11, base_sha=BASE
            )
        self.assertEqual(attestation["verdict"], "UNVERIFIED")
        self.assertTrue(any("exact PR/head/base" in error for error in errors), errors)
        artifact_verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
