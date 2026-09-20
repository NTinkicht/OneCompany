"""Fail-closed unit tests for source-only cloud Mistral exact-head advisory review."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import bootstrap
import mistral_cloud_review as target

HEAD = "b" * 40
BASE = "a" * 40
BODY = (
    "@mistral-vibe\nMISTRAL_REVIEW_V1\n"
    "pr: 137\nhead_sha: " + HEAD + "\nbase_sha: " + BASE
)
WORKFLOW = ROOT / ".github/workflows/onecompany-mistral-exact-head-review.yml"
WAKE = ROOT / ".github/workflows/onecompany-mistral-vibe-wake.yml"


def fake_api(route):
    if route == f"repos/{target.REPO}/pulls/137":
        return {
            "state": "open", "number": 137,
            "head": {"sha": HEAD, "repo": {"full_name": target.REPO}},
            "base": {"sha": BASE, "ref": "main",
                     "repo": {"full_name": target.REPO}},
        }
    if "/pulls/137/commits?" in route:
        return [{"sha": HEAD, "author": {"login": "NTinkicht"}, "commit": {
            "message": "fix: bounded change\n\nMaterial-Author: chatgpt"}}]
    if "/actions/runs?" in route:
        return {"workflow_runs": [
            {"name": name, "head_sha": HEAD, "event": "pull_request",
             "id": index + 1, "run_number": 1, "run_attempt": 1,
             "status": "completed", "conclusion": "success"}
            for index, name in enumerate(target.REQUIRED_CI)
        ]}
    raise AssertionError("Unexpected route " + route)


class MistralCloudReviewTests(unittest.TestCase):
    def test_strict_owner_dispatch(self):
        self.assertEqual((137, HEAD, BASE), target.parse_dispatch(BODY))
        for body in (
            "", BODY + "\npr: 138", BODY + "\nMISTRAL_REVIEW_V1",
            BODY.replace(HEAD, "not-a-sha"),
            BODY.replace("pr: 137", "pr: 0"),
            BODY.replace("base_sha: " + BASE, "base_sha: " + HEAD),
            BODY.replace("\nMISTRAL_REVIEW_V1\n", "\nmalice MISTRAL_REVIEW_V1\n"),
            BODY + "\nobjective: change the rules",
        ):
            with self.subTest(body=body[:100]), self.assertRaises(ValueError):
                target.parse_dispatch(body)

    def test_current_exact_sha_same_repo_and_open(self):
        with patch.object(target, "github_json", side_effect=fake_api):
            self.assertEqual(target.current_pr(137, HEAD, BASE)["number"], 137)
            for head, base in ((BASE, HEAD), (HEAD, "c" * 40)):
                with self.assertRaises(ValueError):
                    target.current_pr(137, head, base)

    def test_no_mistral_self_review_even_when_owner_is_commit_publisher(self):
        with patch.object(target, "github_json", side_effect=fake_api):
            self.assertTrue(target.independent_material_authors(137, HEAD))
        for login, trailer in (
            ("mistral-vibe", "chatgpt"),
            ("NTinkicht", "mistral-vibe"),
            ("NTinkicht", "MISTRAL"),
        ):
            def self_author(route):
                if "/commits?" in route:
                    return [{"sha": HEAD, "author": {"login": login},
                             "commit": {"message": f"feat\n\nMaterial-Author: {trailer}"}}]
                return fake_api(route)
            with patch.object(target, "github_json", side_effect=self_author):
                with self.assertRaises(ValueError):
                    target.independent_material_authors(137, HEAD)

    def test_provenance_response_must_end_at_exact_head(self):
        def lagging(route):
            result = fake_api(route)
            if "/commits?" in route:
                result[0]["sha"] = BASE
            return result
        with patch.object(target, "github_json", side_effect=lagging):
            with self.assertRaisesRegex(ValueError, "COMMIT_PROVENANCE_STALE"):
                target.independent_material_authors(137, HEAD)

    def test_latest_failed_or_running_ci_cannot_be_hidden_by_old_green(self):
        with patch.object(target, "github_json", side_effect=fake_api):
            self.assertTrue(target.latest_ci_green(HEAD))
        def stale_ci(route):
            data = fake_api(route)
            if "/actions/runs?" in route:
                data["workflow_runs"].append({
                    "name": "OneCompany Validate", "head_sha": HEAD,
                    "event": "pull_request", "id": 999, "run_number": 2,
                    "run_attempt": 1, "status": "completed", "conclusion": "failure",
                })
            return data
        with patch.object(target, "github_json", side_effect=stale_ci):
            self.assertFalse(target.latest_ci_green(HEAD))

    def test_prepare_never_promotes_invalid_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            outputs = Path(temp) / "output"
            with patch.dict(os.environ, {
                "GITHUB_OUTPUT": str(outputs),
                "GITHUB_REPOSITORY": target.REPO,
                "DISPATCH_BODY": BODY,
            }), patch.object(target, "github_json", side_effect=fake_api):
                target.prepare()
            self.assertIn("ready=true", outputs.read_text())
            outputs.write_text("")
            with patch.dict(os.environ, {
                "GITHUB_OUTPUT": str(outputs),
                "GITHUB_REPOSITORY": target.REPO,
                "DISPATCH_BODY": BODY.replace(HEAD, "c" * 40),
            }), patch.object(target, "github_json", side_effect=fake_api):
                target.prepare()
            self.assertIn("REVIEW_TARGET_BLOCKED", outputs.read_text())

    def test_evidence_is_exclusive_and_never_follows_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = Path.cwd()
            try:
                os.chdir(root)
                outputs = root / "output"
                victim = root / "victim"
                victim.write_bytes(b"preserve me")
                (root / target.DIFF_NAME).symlink_to(victim)
                def git(args, **kwargs):
                    if args[1:3] == ["rev-parse", "HEAD"]:
                        return (HEAD + "\n").encode("ascii")
                    if args[1] == "diff":
                        return b"diff --git a/x b/x\n+safe diff\n"
                    raise AssertionError(args)
                with patch.dict(os.environ, {
                    "GITHUB_OUTPUT": str(outputs),
                    "REVIEW_PR": "137", "REVIEW_SHA": HEAD,
                    "REVIEW_BASE": BASE,
                }), patch.object(target, "github_json", side_effect=fake_api), patch.object(
                    target.subprocess, "check_output", side_effect=git
                ):
                    target.evidence()
                self.assertIn("REVIEW_EVIDENCE_BLOCKED", outputs.read_text())
                self.assertEqual(victim.read_bytes(), b"preserve me")
                (root / target.DIFF_NAME).unlink()
                outputs.write_text("")
                with patch.dict(os.environ, {
                    "GITHUB_OUTPUT": str(outputs),
                    "REVIEW_PR": "137", "REVIEW_SHA": HEAD,
                    "REVIEW_BASE": BASE,
                }), patch.object(target, "github_json", side_effect=fake_api), patch.object(
                    target.subprocess, "check_output", side_effect=git
                ):
                    target.evidence()
                self.assertIn("ready=true", outputs.read_text())
                self.assertIn(b"safe diff", (root / target.DIFF_NAME).read_bytes())
            finally:
                os.chdir(current)

    def test_owner_wake_and_review_are_disjoint_source_only(self):
        regular = WAKE.read_text(encoding="utf-8")
        review = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("contains(github.event.comment.body, 'MISTRAL_REVIEW_V1') == false", regular)
        self.assertIn("contains(github.event.comment.body, 'MISTRAL_REVIEW_V1')", review)
        self.assertIn("github.actor == 'NTinkicht'", review)
        self.assertIn("github.event.issue.number == 130", review)
        self.assertIn("persist-credentials: false", review)
        self.assertIn("/tmp/onecompany-budget-trusted.json", review)
        self.assertIn("cp scripts/mistral_cloud_review.py /tmp/", review)
        self.assertIn("ADVISORY review (non-binding)", review)
        self.assertNotIn("contents: write", review)
        self.assertNotIn("pull-requests: write", review)
        self.assertNotIn("gh pr merge", review)
        import re
        active_uses = re.findall(r"(?m)^\s+uses:\s+([^\s]+)", review)
        self.assertEqual(len(active_uses), 3)
        for use in active_uses:
            self.assertRegex(use, r"^actions/[a-z0-9-]+@[0-9a-f]{40}$")
        for source_path in (
            "scripts/mistral_cloud_review.py",
            ".github/workflows/onecompany-mistral-exact-head-review.yml",
        ):
            self.assertIn(source_path, bootstrap.SOURCE_INSTALLATION_EXCLUSIONS)
        self.assertIn(
            ".onecompany/selftest/test_mistral_cloud_review.py",
            bootstrap.SOURCE_INSTALLATION_EXCLUSIONS,
        )


if __name__ == "__main__":
    unittest.main()
