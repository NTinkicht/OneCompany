from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import evidence_verify


CANDIDATE = "a" * 40
BASE = "b" * 40


class ArtifactEvidenceTests(unittest.TestCase):
    def reference(self, kind: str = "onecompany_quality_json_v1", path: str = "quality.json") -> dict:
        return {
            "id": "EVID-001",
            "provider": "github_actions",
            "source_kind": "artifact",
            "workflow_run_id": 101,
            "artifact_id": 202,
            "artifact_name": "quality-evidence",
            "parser": {"kind": kind, "version": 1, "path": path},
        }

    def workflow(self, *, sha: str = CANDIDATE, conclusion: str = "success") -> dict:
        return {
            "id": 101,
            "name": "Quality Evidence",
            "path": ".github/workflows/quality.yml",
            "event": "pull_request",
            "head_sha": sha,
            "status": "completed",
            "conclusion": conclusion,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:01:00Z",
        }

    def artifact(self) -> dict:
        return {
            "id": 202,
            "name": "quality-evidence",
            "size_in_bytes": 100,
            "expired": False,
            "created_at": "2026-01-01T00:00:30Z",
            "updated_at": "2026-01-01T00:00:30Z",
            "expires_at": "2026-04-01T00:00:30Z",
        }

    def test_wrong_sha_is_rejected_before_artifact_download(self):
        with (
            patch.object(evidence_verify, "_workflow_run", return_value=(self.workflow(sha="c" * 40), None)),
            patch.object(evidence_verify, "_artifacts_for_run") as artifacts,
            patch.object(evidence_verify, "_download_artifact") as download,
        ):
            result = evidence_verify.verify_artifact_reference(
                "owner/repo", CANDIDATE, BASE, self.reference()
            )
        self.assertFalse(result["verified"])
        self.assertTrue(any("not exact candidate" in error for error in result["errors"]), result)
        artifacts.assert_not_called()
        download.assert_not_called()

    def test_missing_artifact_is_unverified(self):
        with (
            patch.object(evidence_verify, "_workflow_run", return_value=(self.workflow(), None)),
            patch.object(evidence_verify, "_artifacts_for_run", return_value=([], None)),
            patch.object(evidence_verify, "_download_artifact") as download,
        ):
            result = evidence_verify.verify_artifact_reference(
                "owner/repo", CANDIDATE, BASE, self.reference()
            )
        self.assertFalse(result["verified"])
        self.assertTrue(any("not found" in error for error in result["errors"]), result)
        download.assert_not_called()

    def test_downloaded_quality_artifact_is_hashed_and_parsed(self):
        def fake_download(repo: str, run_id: int, name: str, destination: Path) -> None:
            (destination / "quality.json").write_text(
                json.dumps(
                    {
                        "schema": "onecompany-quality-evidence-v1",
                        "candidate_sha": CANDIDATE,
                        "base_sha": BASE,
                        "coverage": {
                            "line": 92,
                            "branch": 86,
                            "changed_line": 98,
                            "mutation": 75,
                        },
                        "test_families": {
                            "static": "pass",
                            "unit": "pass",
                            "regression": "pass",
                        },
                        "tool": {"name": "quality-suite", "version": "1"},
                    }
                ),
                encoding="utf-8",
            )
            return None

        with (
            patch.object(evidence_verify, "_workflow_run", return_value=(self.workflow(), None)),
            patch.object(evidence_verify, "_artifacts_for_run", return_value=([self.artifact()], None)),
            patch.object(evidence_verify, "_download_artifact", side_effect=fake_download),
        ):
            result = evidence_verify.verify_artifact_reference(
                "owner/repo", CANDIDATE, BASE, self.reference()
            )
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["extracted"]["coverage"]["mutation"], 75)
        self.assertEqual(result["extracted"]["test_families"]["unit"], "pass")
        digest = result["artifact"]["digest_sha256"]
        self.assertEqual(len(digest), 64)
        self.assertEqual(result["artifact"]["files"], ["quality.json"])

    def test_cobertura_and_junit_are_deterministically_parsed(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "coverage.xml").write_text(
                '<coverage line-rate="0.91" branch-rate="0.83"></coverage>', encoding="utf-8"
            )
            coverage, error = evidence_verify.parse_report(
                root,
                {"kind": "cobertura_xml", "path": "coverage.xml"},
                CANDIDATE,
                BASE,
            )
            self.assertIsNone(error)
            self.assertEqual(coverage["coverage"], {"line": 91.0, "branch": 83.0})

            (root / "junit.xml").write_text(
                '<testsuite tests="3" failures="1" errors="0" skipped="0"></testsuite>',
                encoding="utf-8",
            )
            junit, error = evidence_verify.parse_report(
                root,
                {"kind": "junit_xml", "path": "junit.xml", "family": "unit"},
                CANDIDATE,
                BASE,
            )
            self.assertIsNone(error)
            self.assertEqual(junit["test_families"]["unit"], "fail")

    def test_quality_decision_uses_extracted_values_not_packet_claims(self):
        quality = {
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
        forged_packet_claim = {"mutation": 99}
        extracted = {"line": 90, "branch": 85, "changed_line": 96, "mutation": 40}
        errors = evidence_verify.evaluate_quality(
            quality,
            "production",
            "low",
            True,
            extracted,
            {"static": "pass", "unit": "pass", "regression": "pass"},
        )
        self.assertEqual(forged_packet_claim["mutation"], 99)
        self.assertTrue(any("mutation=40" in error for error in errors), errors)

    def test_review_must_be_platform_approved_on_exact_commit(self):
        review = {
            "id": 303,
            "state": "APPROVED",
            "commit_id": CANDIDATE,
            "user": {"login": "independent-reviewer"},
            "submitted_at": "2026-01-01T00:02:00Z",
        }
        with patch.object(evidence_verify, "_review", return_value=(review, None)):
            result = evidence_verify.verify_review_reference(
                "owner/repo", 11, CANDIDATE, {"review_id": 303}
            )
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["reviewer_login"], "independent-reviewer")

        stale = dict(review, commit_id="c" * 40)
        with patch.object(evidence_verify, "_review", return_value=(stale, None)):
            result = evidence_verify.verify_review_reference(
                "owner/repo", 11, CANDIDATE, {"review_id": 303}
            )
        self.assertFalse(result["verified"])
        self.assertTrue(any("exact candidate" in error for error in result["errors"]), result)

    def test_live_base_or_head_drift_invalidates_context(self):
        live = {
            "state": "open",
            "head": {"sha": CANDIDATE},
            "base": {"sha": "c" * 40},
        }
        with patch.object(evidence_verify, "_pull_request", return_value=(live, None)):
            context, error = evidence_verify.verify_pr_context(
                "owner/repo", 11, CANDIDATE, BASE
            )
        self.assertIsNone(context)
        self.assertIn("base drifted", error)


if __name__ == "__main__":
    unittest.main()
