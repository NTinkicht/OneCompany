from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import platform_identity


def contents_payload(value: dict, sha: str = "a" * 40) -> dict:
    encoded = base64.b64encode(json.dumps(value).encode("utf-8")).decode("ascii")
    return {"encoding": "base64", "content": encoded, "sha": sha}


POLICY = {
    "schema_version": "1.0",
    "trust_model": "base-trusted-platform-principal",
    "principals": [
        {
            "login": "Owner",
            "actor_id": "human-owner",
            "authorities": ["root", "merge_execution", "protected_merge"],
        },
        {"login": "review-bot", "actor_id": "codex", "authorities": ["code_review"]},
    ],
}


class PlatformIdentityTests(unittest.TestCase):
    def test_base_policy_is_used_instead_of_candidate_local_metadata(self):
        def fake(path: str):
            if "/contents/.onecompany/identity.json?ref=" in path:
                return contents_payload(POLICY), None
            raise AssertionError(path)

        with patch.object(platform_identity, "_gh_json", side_effect=fake):
            policy, provenance, errors = platform_identity.load_identity_policy("o/r", "b" * 40)
        self.assertEqual(errors, [])
        self.assertEqual(provenance["source"], "base")
        identity, error = platform_identity.map_platform_login(policy, "Owner")
        self.assertIsNone(error)
        self.assertEqual(identity["actor_id"], "human-owner")
        self.assertNotIn("budget_change", identity["authorities"])

    def test_first_identity_bootstrap_is_repository_owner_only_for_privilege(self):
        def fake(path: str):
            if "/contents/.onecompany/identity.json?ref=" in path:
                return None, "gh: Not Found (HTTP 404)"
            if path == "repos/o/r":
                return {"owner": {"login": "ActualOwner"}}, None
            raise AssertionError(path)

        with patch.object(platform_identity, "_gh_json", side_effect=fake):
            policy, provenance, errors = platform_identity.load_identity_policy("o/r", "b" * 40)
        self.assertEqual(errors, [])
        self.assertEqual(provenance["source"], "repository-owner-bootstrap")
        owner, error = platform_identity.map_platform_login(policy, "ActualOwner")
        self.assertIsNone(error)
        self.assertIn("root", owner["authorities"])
        unknown, unknown_error = platform_identity.map_platform_login(policy, "worker")
        self.assertIsNone(unknown)
        self.assertIn("unknown", unknown_error)

    def test_bootstrap_unknown_exact_reviewer_gets_review_only_authority(self):
        def fake(path: str):
            if path.endswith("/pulls/7/reviews/42"):
                return {
                    "commit_id": "c" * 40,
                    "state": "APPROVED",
                    "submitted_at": "2026-01-01T00:00:00Z",
                    "user": {"login": "Independent"},
                }, None
            if "/contents/.onecompany/identity.json?ref=" in path:
                return None, "gh: Not Found (HTTP 404)"
            if path == "repos/o/r":
                return {"owner": {"login": "ActualOwner"}}, None
            raise AssertionError(path)

        with patch.object(platform_identity, "_gh_json", side_effect=fake):
            identity, errors = platform_identity.review_platform_identity(
                "o/r", 7, 42, "c" * 40, "b" * 40
            )
        self.assertEqual(errors, [])
        self.assertTrue(identity["bootstrap_review_only"])
        self.assertEqual(identity["authorities"], ["code_review"])
        review_ok, _ = platform_identity.require_authority(identity, "code_review")
        merge_ok, merge_reasons = platform_identity.require_authority(identity, "merge_execution")
        root_ok, root_reasons = platform_identity.require_authority(identity, "root")
        self.assertTrue(review_ok)
        self.assertFalse(merge_ok)
        self.assertIn("authority_missing:merge_execution", merge_reasons)
        self.assertFalse(root_ok)
        self.assertIn("authority_missing:root", root_reasons)

    def test_unknown_reviewer_fails_once_base_identity_policy_exists(self):
        def fake(path: str):
            if path.endswith("/pulls/7/reviews/42"):
                return {
                    "commit_id": "c" * 40,
                    "state": "APPROVED",
                    "user": {"login": "Independent"},
                }, None
            if "/contents/.onecompany/identity.json?ref=" in path:
                return contents_payload(POLICY), None
            raise AssertionError(path)

        with patch.object(platform_identity, "_gh_json", side_effect=fake):
            identity, errors = platform_identity.review_platform_identity(
                "o/r", 7, 42, "c" * 40, "b" * 40
            )
        self.assertIsNone(identity)
        self.assertTrue(any("unknown" in error for error in errors), errors)

    def test_spoofed_actor_label_cannot_replace_authenticated_principal(self):
        def fake(path: str):
            if path == "user":
                return {"login": "evil-worker"}, None
            if "/contents/.onecompany/identity.json?ref=" in path:
                return contents_payload(POLICY), None
            raise AssertionError(path)

        with patch.object(platform_identity, "_gh_json", side_effect=fake):
            identity, errors = platform_identity.authorize_current_principal(
                "o/r", "b" * 40, "protected_merge"
            )
        self.assertIsNone(identity)
        self.assertTrue(any("unknown" in error for error in errors), errors)

    def test_unknown_or_ambiguous_principal_fails_closed(self):
        ambiguous = {
            "schema_version": "1.0",
            "trust_model": "base-trusted-platform-principal",
            "principals": [
                {"login": "same", "actor_id": "a", "authorities": ["root"]},
                {"login": "SAME", "actor_id": "b", "authorities": ["code_review"]},
            ],
        }
        errors = platform_identity._validate_policy(ambiguous)
        self.assertTrue(any("ambiguous/duplicated" in error for error in errors), errors)

    def test_review_identity_is_exact_commit_and_base_policy_mapped(self):
        def fake(path: str):
            if path.endswith("/pulls/7/reviews/42"):
                return {
                    "commit_id": "c" * 40,
                    "state": "APPROVED",
                    "submitted_at": "2026-01-01T00:00:00Z",
                    "user": {"login": "review-bot"},
                }, None
            if "/contents/.onecompany/identity.json?ref=" in path:
                return contents_payload(POLICY), None
            raise AssertionError(path)

        with patch.object(platform_identity, "_gh_json", side_effect=fake):
            identity, errors = platform_identity.review_platform_identity(
                "o/r", 7, 42, "c" * 40, "b" * 40
            )
        self.assertEqual(errors, [])
        self.assertEqual(identity["actor_id"], "codex")
        ok, reasons = platform_identity.require_authority(identity, "code_review")
        self.assertTrue(ok, reasons)

    def test_stale_review_identity_fails_closed(self):
        def fake(path: str):
            if path.endswith("/pulls/7/reviews/42"):
                return {
                    "commit_id": "a" * 40,
                    "state": "APPROVED",
                    "user": {"login": "review-bot"},
                }, None
            raise AssertionError(path)

        with patch.object(platform_identity, "_gh_json", side_effect=fake):
            identity, errors = platform_identity.review_platform_identity(
                "o/r", 7, 42, "c" * 40, "b" * 40
            )
        self.assertIsNone(identity)
        self.assertIn("platform review does not target exact candidate SHA", errors)

    def test_material_author_cannot_use_review_authority(self):
        identity = {"actor_id": "codex", "authorities": ["code_review"]}
        ok, reasons = platform_identity.require_authority(identity, "code_review", {"codex"})
        self.assertFalse(ok)
        self.assertIn("material_author_conflict", reasons)


if __name__ == "__main__":
    unittest.main()
