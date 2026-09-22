"""Source-only unit contract for authenticated Grok native cloud PR result bridge."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import grok_cloud_bridge as g

H = "b" * 40
B = "a" * 40
BODY = {
    "version": 1,
    "kind": "review",
    "repo": g.REPO,
    "pr": 99,
    "head_sha": H,
    "base_sha": B,
    "execution_id": "provider-execution-1234",
    "verdict": "CHANGES_REQUIRED",
    "findings": [
        {"severity": "MAJOR", "path": "scripts/demo.py", "line": 15,
         "description": "Bound the output before passing it on"},
    ],
    "summary": "Examined the exact candidate diff and the underlying implementation.",
}


def source(data=BODY):
    return g.MARKER + "\n" + json.dumps(data, sort_keys=True)


def fake_github(route):
    if route.endswith("/pulls/99"):
        return {"number": 99, "state": "open",
                "head": {"sha": H, "repo": {"full_name": g.REPO}},
                "base": {"sha": B, "ref": "main",
                         "repo": {"full_name": g.REPO}}}
    if "/pulls/99/commits?" in route:
        return [{"sha": H, "author": {"login": "NTinkicht"},
                 "commit": {"message": "feat: test\n\nMaterial-Author: chatgpt"}}]
    if "/issues/99/comments?" in route:
        return []
    raise AssertionError(route)


class GrokCloudBridgeTests(unittest.TestCase):
    def test_bot_attributed_exact_head_review_is_advisory_only(self):
        with patch.object(g, "github", side_effect=fake_github), patch(
            "mistral_cloud_review.latest_ci_green", return_value=True
        ):
            result = g.verify(
                source(), actor=g.BOT_LOGIN, repository=g.REPO,
                issue_number=131, source_comment_id=1734,
            )
        self.assertEqual(result["head_sha"], H)
        self.assertEqual(result["source_actor"], g.BOT_LOGIN)
        text = g.comment_text(result)
        self.assertIn("source_comment_id=1734", text)
        self.assertIn(H, text)
        self.assertIn("non-binding", text)
        self.assertIn("No binding gate, approval, code write or merge authority.", text)

    def test_owner_oauth_comment_or_wrong_issue_cannot_impersonate_bot(self):
        for override in (
            {"actor": "NTinkicht"},
            {"actor": "onecompany-grok-worker"},
            {"repository": "NTinkicht/Tabibi"},
            {"issue_number": 130},
            {"source_comment_id": 0},
        ):
            args = {
                "actor": g.BOT_LOGIN, "repository": g.REPO,
                "issue_number": 131, "source_comment_id": 1734,
            }
            args.update(override)
            with self.subTest(args=override), self.assertRaisesRegex(
                ValueError, "IDENTITY_OR_INBOX"
            ):
                g.verify(source(), **args)

    def test_malformed_incomplete_and_oversized_model_results_fail(self):
        for invalid in (
            "", source() + source(), "text\n" + source(),
            source({"version": 1}),
            g.MARKER + "\n" + '{"version":',
            g.MARKER + "\n" + " " * 13_000,
        ):
            with self.subTest(sample=invalid[:35]), self.assertRaises(
                (ValueError, json.JSONDecodeError)
            ):
                g.strict_result(invalid)

    def test_stale_target_or_missing_ci_fail_closed(self):
        with patch.object(g, "github", side_effect=fake_github), patch(
            "mistral_cloud_review.latest_ci_green", return_value=False
        ):
            with self.assertRaisesRegex(ValueError, "GROK_CI_NOT_GREEN"):
                g.verify(source(), actor=g.BOT_LOGIN, repository=g.REPO,
                         issue_number=131, source_comment_id=1734)
        def stale(route):
            result = fake_github(route)
            if route.endswith("/pulls/99"):
                result["head"]["sha"] = "c" * 40
            return result
        with patch.object(g, "github", side_effect=stale), self.assertRaisesRegex(
            ValueError, "GROK_PR_STALE"
        ):
            g.prove_pr_and_independence(BODY)

    def test_nullable_gh_metadata_and_missing_cli_are_safe_failures(self):
        for malformed in (None, [], {"head": None, "base": None},
                          {"head": {"repo": None}, "base": {"repo": None}}):
            with self.subTest(value=repr(malformed)), patch.object(
                g, "github", return_value=malformed
            ), self.assertRaisesRegex(ValueError, "GROK_PR_UNAVAILABLE"):
                g.prove_pr_and_independence(BODY)

    def test_model_material_author_cannot_review_self(self):
        for author, trailer in (
            ("onecompany-grok-worker[bot]", "chatgpt"),
            ("NTinkicht", "grok-4-6-interactive"),
            ("NTinkicht", "grok"),
        ):
            def self_author(route):
                result = fake_github(route)
                if "/commits?" in route:
                    result[0]["author"]["login"] = author
                    result[0]["commit"]["message"] = (
                        "feat: model edit\n\nMaterial-Author: " + trailer
                    )
                return result
            with patch.object(g, "github", side_effect=self_author), self.assertRaisesRegex(
                ValueError, "GROK_SELF_REVIEW"
            ):
                g.prove_pr_and_independence(BODY)

    def test_grok_committer_is_not_independent_even_with_owner_author(self):
        def committer(route):
            result = fake_github(route)
            if "/commits?" in route:
                result[0]["committer"] = {"login": g.BOT_LOGIN}
                result[0]["commit"]["message"] = "feat: no trailers"
            return result
        with patch.object(g, "github", side_effect=committer):
            with self.assertRaisesRegex(ValueError, "GROK_SELF_REVIEW_BLOCKED"):
                g.prove_pr_and_independence(BODY)

    def test_duplicate_source_comment_is_idempotently_rejected(self):
        def duplicate(route):
            if "/issues/99/comments?" in route:
                return [{"user": {"login": "github-actions[bot]"},
                         "body": "source_comment_id=1734"}]
            return fake_github(route)
        with patch.object(g, "github", side_effect=duplicate), patch(
            "mistral_cloud_review.latest_ci_green", return_value=True
        ), self.assertRaisesRegex(ValueError, "DUPLICATE_SOURCE_COMMENT"):
            g.verify(source(), actor=g.BOT_LOGIN, repository=g.REPO,
                     issue_number=131, source_comment_id=1734)

    def test_verdict_and_findings_are_never_model_authority(self):
        for field, malformed in (
            ("verdict", "APPROVED"),
            ("execution_id", "same"),
            ("head_sha", B),
            ("pr", True),
        ):
            mutated = copy.deepcopy(BODY)
            mutated[field] = malformed
            with self.subTest(field=field), self.assertRaises(ValueError):
                g.strict_result(source(mutated))
        mutated = copy.deepcopy(BODY)
        mutated["verdict"] = "NO_BLOCKING_FINDINGS"
        with self.assertRaisesRegex(ValueError, "VERDICT_INCONSISTENT"):
            g.strict_result(source(mutated))
        for path in ("../secrets", "/etc/passwd", ".git/config"):
            mutated = copy.deepcopy(BODY)
            mutated["findings"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                g.strict_result(source(mutated))

    def test_bot_workflow_is_source_only_and_no_merge_code_permissions(self):
        workflow = (
            ROOT / ".github/workflows/onecompany-grok-native-evidence.yml"
        ).read_text()
        self.assertIn("github.actor == 'onecompany-grok-worker[bot]'", workflow)
        self.assertIn("issues: write", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("gh pr merge", workflow)
        self.assertNotIn("git push", workflow)
        self.assertIn("issues/comments/$NEW_COMMENT_ID", workflow)
        self.assertIn("GROK_ADVISORY_RETRACTED_STALE_HEAD", workflow)
        self.assertIn("GROK_RESULT_V1", workflow)


if __name__ == "__main__":
    unittest.main()
