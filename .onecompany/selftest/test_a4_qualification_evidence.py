from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import a4_pr_producer as producer
import a4_qualify as qualifier
from test_a4_first_pr_producer import BASE, FakeGitHub, installation


class PilotApi(FakeGitHub):
    """Synthetic GitHub audit records; NOT a completed live project pilot."""

    def __init__(self, repo: str):
        super().__init__(repo)
        self.run_success = True
        self.step_success = True
        self.ci_success = True
        self.run_path = qualifier.WORKFLOW_PATH
        self.record = None
        self.run_id = 42
        self.job_id = 97
        self.ci_run_id = 84
        self.ci_path = qualifier.TRUSTED_CI_WORKFLOW_PATH
        self.ci_blob = qualifier.TRUSTED_CI_WORKFLOW_BLOB
        self.trusted_app_slug = "github-actions"
        self.wrap_base64 = False

    def call(self, method, path, payload=None):
        """Return provider-shaped workflow/job/check results for refusal tests."""
        if method == "GET" and path.startswith("/compare/"):
            original = super().call(method, path, payload)
            original.update({"status": "ahead", "total_commits": 1})
            return original
        if method == "GET" and path == "/actions/runs/84":
            return {
                "id": self.ci_run_id, "path": self.ci_path,
                "head_sha": self.refs["onecompany-a4-" + self.record["work_unit"].lower()],
                "status": "completed", "conclusion": "success",
                "repository": {"full_name": self.repository},
            }
        if method == "GET" and path == "/contents/" + qualifier.TRUSTED_CI_WORKFLOW_PATH + "?ref=" + BASE:
            return {"type": "file", "sha": self.ci_blob}
        if method == "GET" and path == "/actions/runs/42":
            return {
                "id": self.run_id, "event": "repository_dispatch",
                "path": self.run_path, "head_sha": BASE,
                "status": "completed",
                "conclusion": "success" if self.run_success else "failure",
                "run_attempt": 1,
                "repository": {"full_name": self.repository},
            }
        if method == "GET" and path == "/actions/runs/42/jobs?per_page=100":
            return {"jobs": [{
                "id": self.job_id, "run_id": self.run_id,
                "name": qualifier.PRODUCER_JOB,
                "status": "completed",
                "conclusion": "success" if self.run_success else "failure",
                "steps": [{
                    "name": qualifier.PRODUCER_STEP, "status": "completed",
                    "conclusion": "success" if self.step_success else "skipped",
                }],
            }]}
        if method == "GET" and path.startswith("/commits/") and path.endswith("/check-runs?per_page=100"):
            head = path.split("/commits/", 1)[1].split("/", 1)[0]
            return {"check_runs": [{
                "name": qualifier.TRUSTED_CI_CHECK_NAME, "head_sha": head,
                "status": "completed",
                "conclusion": "success" if self.ci_success else "failure",
                "app": {"slug": self.trusted_app_slug},
                "details_url": (
                    f"https://github.com/{self.repository}/actions/runs/"
                    f"{self.ci_run_id}/job/100"
                ),
            }]}
        if method == "GET" and path.startswith("/contents/docs/") and self.wrap_base64:
            result = super().call(method, path, payload)
            encoded = result["content"]
            result["content"] = encoded[:45] + "\n" + encoded[45:]
            return result
        return super().call(method, path, payload)


def installed(api: PilotApi, wu: str) -> dict:
    """Create one test-only fixture and synthetic run-bound evidence record."""
    result = producer.produce(api, **installation(api.repository, wu))
    api.record = {**result, "run_id": api.run_id, "run_attempt": 1}
    return {
        "repository": api.repository, "work_unit": wu, "actor": "fixture-bot",
        "pr": result["pr"], "head": result["head"], "base": BASE,
        "workflow_run": api.run_id,
        "check_name": qualifier.TRUSTED_CI_CHECK_NAME,
        "ci_workflow_run": api.ci_run_id, "ci_workflow_path": api.ci_path,
    }


class A4QualificationEvidenceTests(unittest.TestCase):
    """Reject a fabricated pilot when any immutable audit binding is missing."""

    def setUp(self):
        """Build two independent fake installations, never touching GitHub."""
        self.first = PilotApi("owner-a/disposable-a")
        self.second = PilotApi("owner-b/disposable-b")
        self.entries = [
            installed(self.first, "WU-A"), installed(self.second, "WU-B"),
        ]
        self.registry = {
            self.first.repository: self.first,
            self.second.repository: self.second,
        }

    def verify(self):
        """Replace network and job-log reads with deterministic local results."""
        with (
            patch.object(
                qualifier, "GitHub",
                side_effect=lambda repo, token: self.registry[repo],
            ),
            patch.object(
                qualifier, "_job_log",
                side_effect=lambda api, job_id: (
                    "2026-09-19T12:00:00Z "
                    + qualifier.EVIDENCE_PREFIX
                    + json.dumps(api.record, sort_keys=True)
                    + "\n"
                ),
            ),
        ):
            return qualifier.verify_pair(self.entries, "read-only-token")

    def test_distinct_owner_exact_run_evidence_is_admissible(self):
        """Require a pair of individually proven project-scoped trial records."""
        result = self.verify()
        self.assertEqual(result["result"], "TWO_REAL_ISOLATED_A4_PILOTS_VERIFIED")
        self.assertEqual(len(result["installations"]), 2)

    def test_same_owner_is_not_two_independent_installations(self):
        """Reject two separately named repos sharing the same GitHub owner."""
        self.entries[1]["repository"] = "owner-a/other-repo"
        with self.assertRaisesRegex(producer.Refused, "distinct_owners"):
            self.verify()

    def test_unrelated_successful_workflow_does_not_prove_producer(self):
        """Reject valid but unrelated repository-dispatch run records."""
        self.first.run_path = ".github/workflows/unrelated.yml"
        with self.assertRaisesRegex(producer.Refused, "run_not_proven"):
            self.verify()

    def test_skipped_job_step_cannot_substitute_for_execution(self):
        """Reject a workflow with an absent or skipped producer step."""
        self.first.step_success = False
        with self.assertRaisesRegex(producer.Refused, "job_not_successful"):
            self.verify()

    def test_same_workflow_but_foreign_result_is_refused(self):
        """Bind producer log to the exact WU, PR, head, base and run."""
        self.first.record["head"] = "e" * 40
        with self.assertRaisesRegex(producer.Refused, "evidence_identity_mismatch"):
            self.verify()

    def test_run_attempt_mismatch_is_refused(self):
        """Prevent a stale result from satisfying a later run attempt."""
        self.first.record["run_attempt"] = 99
        with self.assertRaisesRegex(producer.Refused, "evidence_identity_mismatch"):
            self.verify()

    def test_additional_policy_file_in_claim_is_refused(self):
        """Reject additional files even when the fixture body is correct."""
        self.first.extra_diff = True
        with self.assertRaisesRegex(producer.Refused, "outside_fixture"):
            self.verify()

    def test_github_wrapped_base64_content_is_valid(self):
        """Accept GitHub\\u0027s line-wrapped Base64 but require exact decoded bytes."""
        self.first.wrap_base64 = True
        self.assertEqual(self.verify()["result"], "TWO_REAL_ISOLATED_A4_PILOTS_VERIFIED")

    def test_forged_or_untrusted_ci_check_is_refused(self):
        """Reject arbitrary check names or a check from an untrusted app."""
        self.first.trusted_app_slug = "untrusted-app"
        with self.assertRaisesRegex(producer.Refused, "exact_head_ci_not_proven"):
            self.verify()
        self.first.trusted_app_slug = "github-actions"
        self.first.ci_path = ".github/workflows/unrelated.yml"
        with self.assertRaisesRegex(producer.Refused, "trusted_exact_head_ci_run"):
            self.verify()

    def test_manifest_selected_ci_workflow_is_refused(self):
        """Do not let evidence provider select its own validation workflow."""
        self.entries[0]["ci_workflow_path"] = ".github/workflows/unrelated.yml"
        with self.assertRaisesRegex(producer.Refused, "not_approved"):
            self.verify()
        self.entries[0]["ci_workflow_path"] = qualifier.TRUSTED_CI_WORKFLOW_PATH
        self.first.ci_blob = "f" * 40
        with self.assertRaisesRegex(producer.Refused, "blob_mismatch"):
            self.verify()

    def test_private_disposable_pilot_cannot_be_qualified(self):
        """Reject a target with private or uncertain Actions billing."""
        self.first.private = True
        self.first.visibility = "private"
        with self.assertRaisesRegex(producer.Refused, "public_disposable_runner"):
            self.verify()

    def test_no_exact_head_green_ci_is_refused(self):
        """Producer completion never substitutes for deterministic CI."""
        self.first.ci_success = False
        with self.assertRaisesRegex(producer.Refused, "exact_head_ci_not_proven"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
