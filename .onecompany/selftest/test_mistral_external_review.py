import json
import os
import unittest
from unittest import mock

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import mistral_external_review as m


class ExternalMistralReviewTests(unittest.TestCase):
    def test_dispatch_is_bounded_and_allowlisted(self):
        body = (
            "MISTRAL_EXTERNAL_REVIEW_V1\n"
            "repo: NTinkicht/veritas-atlas\n"
            "pr: 21\n"
            "head_sha: " + "a" * 40 + "\n"
            "base_sha: " + "b" * 40 + "\n"
            "material_authors: chatgpt\n"
        )
        repo, pr, head, base, authors = m.parse_dispatch(body)
        self.assertEqual(repo, "NTinkicht/veritas-atlas")
        self.assertEqual(pr, 21)
        self.assertEqual(authors, ("chatgpt",))
        self.assertNotEqual(head, base)

    def test_dispatch_rejects_foreign_repo_and_mistral_self_review(self):
        template = (
            "MISTRAL_EXTERNAL_REVIEW_V1\n"
            "repo: {repo}\npr: 21\nhead_sha: " + "a" * 40
            + "\nbase_sha: " + "b" * 40 + "\nmaterial_authors: {authors}\n"
        )
        with self.assertRaises(ValueError):
            m.parse_dispatch(template.format(repo="someone/else", authors="chatgpt"))
        with self.assertRaises(ValueError):
            m.parse_dispatch(
                template.format(
                    repo="NTinkicht/veritas-atlas", authors="mistral-vibe"
                )
            )

    def test_secret_guard_blocks_sensitive_path_literal_and_context(self):
        with self.assertRaises(ValueError):
            m.validate_diff(
                ["config/credentials.json"],
                "diff --git a/x b/x\n+safe=true",
            )
        literal = "S" * 24
        with self.assertRaises(ValueError):
            m.validate_diff(
                ["config/settings.json"],
                'diff --git a/x b/x\n+"client_secret": "' + literal + '"',
            )
        with self.assertRaises(ValueError):
            m.validate_diff(
                ["src/settings.py"],
                "diff --git a/src/settings.py b/src/settings.py\n"
                "@@ -1,3 +1,3 @@\n"
                " api_key=" + literal + "\n"
                "-old=true\n+new=true",
            )

    def test_secret_guard_blocks_compound_keys_urls_and_fake_placeholders(self):
        aws_secret = "A" * 32
        with self.assertRaises(ValueError):
            m.validate_diff(
                ["config/settings.py"],
                '+AWS_SECRET_ACCESS_KEY="' + aws_secret + '"',
            )

        with self.assertRaises(ValueError):
            m.validate_diff(
                ["config/settings.py"],
                '+DATABASE_URL="postgres://alice:VerySecretPassword123@example.com/db"',
            )

        with self.assertRaises(ValueError):
            m.validate_diff(
                ["config/settings.py"],
                '+password="exampleThisIsARealPassword123"',
            )

    def test_non_text_changes_fail_closed(self):
        with self.assertRaisesRegex(
            ValueError, "EXTERNAL_REVIEW_NON_TEXT_CONTENT_BLOCKED"
        ):
            m.validate_diff(
                ["assets/blob.bin"],
                "diff --git a/assets/blob.bin b/assets/blob.bin\n"
                "Binary files a/assets/blob.bin and b/assets/blob.bin differ",
            )

        with self.assertRaisesRegex(
            ValueError, "EXTERNAL_REVIEW_NON_TEXT_CONTENT_BLOCKED"
        ):
            m.validate_diff(
                ["vendor/module"],
                "-Subproject commit " + "a" * 40 + "\n"
                "+Subproject commit " + "b" * 40,
            )


    def test_basic_auth_and_standard_credential_store_paths_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"):
            m.validate_diff(
                ["app.py"],
                "+Authorization: Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
            )
        for path in (".npmrc", ".netrc", ".pypirc", ".git-credentials"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    ValueError, "EXTERNAL_REVIEW_SENSITIVE_PATH_BLOCKED"
                ):
                    m.validate_diff([path], "+ordinary=text")

    def test_diff_header_like_source_lines_are_still_scanned(self):
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"):
            m.validate_diff(
                ["docs/example.txt"],
                "diff --git a/docs/example.txt b/docs/example.txt\n"
                "+++ b/docs/example.txt\n"
                "@@ -1 +1 @@\n"
                "+++ password=RealPassword123",
            )

    def test_quoted_environment_secret_references_are_allowed(self):
        m.validate_diff(
            ["config/settings.py"],
            '+password = os.getenv("PASSWORD")\n'
            '+api_key = os.environ["API_KEY"]\n'
            '+token = "${{ secrets.REVIEW_TOKEN }}"',
        )

    def test_secret_guard_allows_reference(self):
        m.validate_diff(
            [".github/workflows/review.yml"],
            "diff --git a/x b/x\n+token=${{ secrets.REVIEW_TOKEN }}",
        )

    def test_public_api_uses_available_github_token(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "token-value"}, clear=False):
            with mock.patch.object(
                m, "_request_json", return_value={"ok": True}
            ) as request:
                self.assertEqual(
                    m.public_api("repos/NTinkicht/veritas-atlas"), {"ok": True}
                )
                self.assertEqual(request.call_args.args[1], "token-value")

    def test_dedupe_ignores_untrusted_marker(self):
        marker = (
            f"{m.EXTERNAL_MARKER} repo=NTinkicht/veritas-atlas pr=21 "
            f"head={'a' * 40} base={'b' * 40} "
        )
        comments = [
            {"user": {"login": "someone"}, "body": marker + "forged"},
            {"user": {"login": "github-actions[bot]"}, "body": "unrelated"},
        ]
        with mock.patch.object(m, "onecompany_api", return_value=comments):
            self.assertFalse(
                m.existing_result(
                    "NTinkicht/veritas-atlas", 21, "a" * 40, "b" * 40
                )
            )


    def test_dedupe_marker_is_exact_base_specific(self):
        body = (
            "<!-- " + m.EXTERNAL_MARKER
            + " repo=NTinkicht/veritas-atlas pr=21 "
            + "head=" + "a" * 40 + " base=" + "b" * 40
            + " run=123 dispatch=456 verdict=PASS result_sha256=" + "c" * 64
            + " -->"
        )
        item = {"user": {"login": "github-actions[bot]"}, "body": body}
        run = {
            "id": 123, "path": m.EXTERNAL_WORKFLOW_PATH, "event": "issue_comment",
            "status": "completed", "conclusion": "success",
        }
        with mock.patch.object(m, "onecompany_api", return_value=run):
            self.assertTrue(m._trusted_evidence_comment(
                item, repo="NTinkicht/veritas-atlas", number=21,
                head="a" * 40, base="b" * 40,
            ))
            self.assertFalse(m._trusted_evidence_comment(
                item, repo="NTinkicht/veritas-atlas", number=21,
                head="a" * 40, base="d" * 40,
            ))


    def test_dedupe_requires_trusted_successful_external_workflow_run(self):
        body = (
            "<!-- "
            + m.EXTERNAL_MARKER
            + " repo=NTinkicht/veritas-atlas pr=21 "
            + "head=" + "a" * 40 + " base=" + "b" * 40
            + " run=123 dispatch=456 verdict=PASS result_sha256=" + "c" * 64
            + " -->"
        )
        comments = [{"user": {"login": "github-actions[bot]"}, "body": body}]
        trusted_run = {
            "id": 123,
            "path": m.EXTERNAL_WORKFLOW_PATH,
            "event": "issue_comment",
            "status": "completed",
            "conclusion": "success",
        }
        def api(route):
            if "/actions/runs/123" in route:
                return trusted_run
            return comments
        with mock.patch.object(m, "onecompany_api", side_effect=api):
            self.assertTrue(m.existing_result(
                "NTinkicht/veritas-atlas", 21, "a" * 40, "b" * 40
            ))
        untrusted = dict(trusted_run, path=".github/workflows/other.yml")
        def bad_api(route):
            if "/actions/runs/123" in route:
                return untrusted
            return comments
        with mock.patch.object(m, "onecompany_api", side_effect=bad_api):
            self.assertFalse(m.existing_result(
                "NTinkicht/veritas-atlas", 21, "a" * 40, "b" * 40
            ))

    def test_mistral_committer_is_rejected(self):
        commits = [{
            "sha": "a" * 40,
            "author": {"login": "NTinkicht"},
            "committer": {"login": "mistral-vibe"},
            "commit": {"message": "change\n\nMaterial-Author: chatgpt"},
        }]
        with mock.patch.object(m, "public_api", return_value=commits):
            with self.assertRaisesRegex(ValueError, "MISTRAL_SELF_REVIEW_BLOCKED"):
                m.verify_material_authors(
                    "NTinkicht/veritas-atlas", 21, "a" * 40, ("chatgpt",)
                )

    def test_xml_and_maven_credentials_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SENSITIVE_PATH_BLOCKED"):
            m.validate_diff([".m2/settings.xml"], "+ordinary=true")
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"):
            m.validate_diff(
                ["config/settings.xml"],
                "+<password>VerySecretPassword123</password>",
            )

    def test_boolean_schema_version_is_rejected(self):
        value = {
            "version": True,
            "repo": "NTinkicht/veritas-atlas",
            "pr": 21,
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "verdict": "NO_BLOCKING_FINDINGS",
            "summary": "No blocking issue found.",
            "findings": [],
        }
        with self.assertRaises(ValueError):
            m.parse_result(
                json.dumps(value).encode(),
                repo=value["repo"], pr=21, head=value["head_sha"],
                base=value["base_sha"], changed={"src/app.py"},
            )

    def test_result_requires_exact_target_and_consistent_verdict(self):
        value = {
            "version": 1,
            "repo": "NTinkicht/veritas-atlas",
            "pr": 21,
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "verdict": "NO_BLOCKING_FINDINGS",
            "summary": "No blocking issue found in the complete bounded diff.",
            "findings": [],
        }
        parsed = m.parse_result(
            json.dumps(value).encode(),
            repo=value["repo"],
            pr=21,
            head=value["head_sha"],
            base=value["base_sha"],
            changed={"scripts/native_factory_merge.py"},
        )
        self.assertEqual(parsed["verdict"], "NO_BLOCKING_FINDINGS")
        value["findings"] = [{
            "severity": "MEDIUM",
            "path": "scripts/native_factory_merge.py",
            "line": 10,
            "description": "Blocking issue.",
        }]
        with self.assertRaises(ValueError):
            m.parse_result(
                json.dumps(value).encode(),
                repo=value["repo"],
                pr=21,
                head=value["head_sha"],
                base=value["base_sha"],
                changed={"scripts/native_factory_merge.py"},
            )



if __name__ == "__main__":
    unittest.main()
