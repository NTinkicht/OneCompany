"""An Actions-bot GitHub approval is binding ONLY with live protected Mistral provenance."""
from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import platform_identity as identity

REPO = "NTinkicht/OneCompany"
BASE = "b" * 40
HEAD = "c" * 40
TIP = "d" * 40
RUN_SHA = "e" * 40
RUN_ID = 12345
MARKER = (
    f"<!-- ONECOMPANY_MISTRAL_BINDING_REVIEW_V1 pr=220 "
    f"head={HEAD} base={BASE} run={RUN_ID} "
    f"run_sha={RUN_SHA} verdict=PASS -->"
)
POLICY = {
    "schema_version": "1.0",
    "trust_model": "base-trusted-platform-principal",
    "principals": [
        {"login": "NTinkicht", "actor_id": "human-owner",
         "authorities": ["root", "code_review"]},
    ],
}


class MistralBindingIdentityTests(unittest.TestCase):
    def fake_api(self, overrides=None):
        overrides = overrides or {}
        review = {
            "user": {"login": "github-actions[bot]"},
            "state": "APPROVED", "commit_id": HEAD,
            "submitted_at": "2026-09-25T15:15:00Z",
            "body": MARKER,
        }
        run = {
            "path": identity.MISTRAL_WORKFLOW, "status": "completed",
            "conclusion": "success", "event": "issue_comment",
            "head_branch": "main", "head_sha": RUN_SHA,
            "actor": {"login": "NTinkicht"},
            "triggering_actor": {"login": "NTinkicht"},
            "repository": {"full_name": REPO},
        }
        review.update(overrides.get("review", {}))
        run.update(overrides.get("run", {}))
        encoded = base64.b64encode(json.dumps(POLICY).encode()).decode()
        def fake(path):
            if path == f"repos/{REPO}/pulls/220/reviews/14":
                return review, None
            if path == f"repos/{REPO}/actions/runs/{RUN_ID}":
                return run, None
            if path == f"repos/{REPO}":
                return {"default_branch": "main",
                        "owner": {"login": "NTinkicht", "type": "User"}}, None
            if path == f"repos/{REPO}/branches/main":
                return {"commit": {"sha": TIP}}, None
            if path in (
                f"repos/{REPO}/compare/{BASE}...{TIP}",
                f"repos/{REPO}/compare/{RUN_SHA}...{TIP}",
            ):
                return {"status": "ahead"}, None
            if path == f"repos/{REPO}/contents/.onecompany/identity.json?ref={BASE}":
                return {"encoding": "base64", "sha": "a" * 40,
                        "content": encoded}, None
            raise AssertionError(path)
        return fake

    def test_live_protected_main_model_approval_maps_to_mistral_only(self):
        with patch.object(identity, "_gh_json", side_effect=self.fake_api()):
            reviewer, errors = identity.review_platform_identity(
                REPO, 220, 14, HEAD, BASE)
        self.assertEqual(errors, [])
        self.assertEqual(reviewer["actor_id"], "mistral-vibe")
        self.assertEqual(reviewer["verified_mistral_run_id"], RUN_ID)
        self.assertEqual(reviewer["authorities"], ["code_review"])
        self.assertTrue(identity.require_authority(
            reviewer, "code_review", {"chatgpt"})[0])
        self.assertFalse(identity.require_authority(
            reviewer, "code_review", {"mistral-vibe"})[0])
        self.assertFalse(identity.require_authority(
            reviewer, "merge_execution")[0])

    def test_plain_actions_bot_or_fake_marker_never_grants_review(self):
        for body in ("", "I approve", MARKER.replace("verdict=PASS", "verdict=FAIL"),
                     MARKER.replace("base=" + BASE, "base=" + HEAD),
                     MARKER + "\n" + MARKER):
            with self.subTest(body=body[:60]), patch.object(
                identity, "_gh_json",
                side_effect=self.fake_api({"review": {"body": body}})
            ):
                reviewer, errors = identity.review_platform_identity(
                    REPO, 220, 14, HEAD, BASE)
                self.assertIsNone(reviewer)
                self.assertTrue(errors)

    def test_foreign_or_failed_run_cannot_launder_bot_review(self):
        cases = [
            {"path": ".github/workflows/other.yml"},
            {"event": "pull_request"},
            {"head_branch": "candidate"},
            {"head_sha": HEAD},
            {"status": "in_progress"},
            {"conclusion": "failure"},
            {"actor": {"login": "attacker"}},
            {"triggering_actor": {"login": "attacker"}},
            {"repository": {"full_name": "other/repo"}},
        ]
        for override in cases:
            with self.subTest(override=override), patch.object(
                identity, "_gh_json",
                side_effect=self.fake_api({"run": override})
            ):
                reviewer, errors = identity.review_platform_identity(
                    REPO, 220, 14, HEAD, BASE)
                self.assertIsNone(reviewer)
                self.assertTrue(errors)

    def test_workflow_run_not_in_protected_main_history_is_blocked(self):
        fake = self.fake_api()
        def replaced(path):
            if path == f"repos/{REPO}/compare/{RUN_SHA}...{TIP}":
                return {"status": "diverged"}, None
            return fake(path)
        with patch.object(identity, "_gh_json", side_effect=replaced):
            reviewer, errors = identity.review_platform_identity(
                REPO, 220, 14, HEAD, BASE)
        self.assertIsNone(reviewer)
        self.assertIn("mistral_binding_run_not_in_protected_main_history", errors)

    def test_changes_requested_is_not_approving_platform_review(self):
        with patch.object(
            identity, "_gh_json",
            side_effect=self.fake_api({"review": {"state": "CHANGES_REQUESTED"}})
        ):
            reviewer, errors = identity.review_platform_identity(
                REPO, 220, 14, HEAD, BASE)
        self.assertIsNone(reviewer)
        self.assertTrue(any("state" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
