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

    def test_dispatch_rejects_normalized_mistral_identity_variants(self):
        template = (
            "MISTRAL_EXTERNAL_REVIEW_V1\n"
            "repo: NTinkicht/veritas-atlas\npr: 21\nhead_sha: " + "a" * 40
            + "\nbase_sha: " + "b" * 40 + "\nmaterial_authors: {author}\n"
        )
        for author in ("mistral-vibe-cloud", "mistral_vibe_worker", "mistral-reviewer"):
            with self.subTest(author=author):
                with self.assertRaisesRegex(ValueError, "MISTRAL_SELF_REVIEW_BLOCKED"):
                    m.parse_dispatch(template.format(author=author))

    def test_secret_guard_blocks_standalone_provider_credentials(self):
        samples = (
            "ghp_" + "A" * 36,
            "github_pat_" + "A" * 30,
            "AKIA" + "A" * 16,
            "sk-" + "A" * 32,
            "xoxb-" + "A" * 30,
        )
        for secret in samples:
            with self.subTest(prefix=secret[:8]):
                with self.assertRaisesRegex(
                    ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"
                ):
                    m.validate_diff(
                        ["src/client.py"],
                        "diff --git a/src/client.py b/src/client.py\n"
                        "@@ -1 +1 @@\n+client.connect(\"" + secret + "\")",
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


    def _proof(self, *, base=None):
        base = base or "b" * 40
        body = (
            "<!-- " + m.EXTERNAL_MARKER
            + " repo=NTinkicht/veritas-atlas pr=21 "
            + "head=" + "a" * 40 + " base=" + base
            + " run=123 dispatch=456 verdict=PASS result_sha256=" + "c" * 64
            + " -->"
        )
        item = {
            "id": 789,
            "html_url": "https://github.com/NTinkicht/OneCompany/issues/130#issuecomment-789",
            "user": {"login": "github-actions[bot]"},
            "body": body,
        }
        proof = {
            "version": 1,
            "target": {
                "repo": "NTinkicht/veritas-atlas",
                "pr": 21,
                "head_sha": "a" * 40,
                "base_sha": base,
            },
            "run_id": 123,
            "dispatch_comment_id": 456,
            "published_comment_id": 789,
            "published_comment_url": item["html_url"],
            "publisher": "github-actions[bot]",
            "verdict": "PASS",
            "result_sha256": "c" * 64,
            "body_sha256": m.hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }
        return item, proof

    def test_dedupe_marker_is_exact_base_specific(self):
        item, proof = self._proof()
        run = {
            "id": 123,
            "path": m.EXTERNAL_WORKFLOW_PATH,
            "event": "issue_comment",
            "status": "completed",
            "conclusion": "success",
        }
        with mock.patch.object(m, "onecompany_api", return_value=run), \
             mock.patch.object(m, "_artifact_proof", return_value=proof):
            self.assertTrue(m._trusted_evidence_comment(
                item, repo="NTinkicht/veritas-atlas", number=21,
                head="a" * 40, base="b" * 40,
            ))
            self.assertFalse(m._trusted_evidence_comment(
                item, repo="NTinkicht/veritas-atlas", number=21,
                head="a" * 40, base="d" * 40,
            ))

    def test_dedupe_requires_trusted_successful_external_workflow_run(self):
        item, proof = self._proof()
        comments = [item]
        run = {
            "id": 123,
            "path": m.EXTERNAL_WORKFLOW_PATH,
            "event": "issue_comment",
            "status": "completed",
            "conclusion": "success",
        }
        def api(route):
            if "/issues/130/comments" in route:
                return comments
            if "/actions/runs/123" in route:
                return run
            raise AssertionError(route)
        with mock.patch.object(m, "onecompany_api", side_effect=api), \
             mock.patch.object(m, "_artifact_proof", return_value=proof):
            self.assertTrue(m.existing_result(
                "NTinkicht/veritas-atlas", 21, "a" * 40, "b" * 40
            ))

    def test_orphan_published_comment_without_run_proof_is_retryable(self):
        item, _proof = self._proof()
        comments = [item]
        run = {
            "id": 123,
            "path": m.EXTERNAL_WORKFLOW_PATH,
            "event": "issue_comment",
            "status": "completed",
            "conclusion": "success",
        }

        def api(route):
            if "/issues/130/comments" in route:
                return comments
            if "/actions/runs/123" in route:
                return run
            raise AssertionError(route)

        with mock.patch.object(m, "onecompany_api", side_effect=api), \
             mock.patch.object(m, "_artifact_proof", return_value=None):
            self.assertFalse(m.existing_result(
                "NTinkicht/veritas-atlas", 21, "a" * 40, "b" * 40
            ))

    def test_result_text_bounds_keep_total_contract_bounded(self):
        value = {
            "version": 1,
            "repo": "NTinkicht/veritas-atlas",
            "pr": 21,
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "verdict": "NO_BLOCKING_FINDINGS",
            "summary": "s" * 1201,
            "findings": [],
        }
        with self.assertRaises(ValueError):
            m.parse_result(
                json.dumps(value).encode(),
                repo=value["repo"], pr=21, head=value["head_sha"],
                base=value["base_sha"], changed={"src/app.py"},
            )
        value["summary"] = "ok"
        value["findings"] = [{
            "severity": "LOW", "path": "src/app.py", "line": 1,
            "description": "d" * 801,
        }]
        with self.assertRaises(ValueError):
            m.parse_result(
                json.dumps(value).encode(),
                repo=value["repo"], pr=21, head=value["head_sha"],
                base=value["base_sha"], changed={"src/app.py"},
            )

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


    def test_dotted_and_camel_secret_keys_are_blocked_without_author_false_positive(self):
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"):
            m.validate_diff(
                ["config/application.properties"],
                "+spring.datasource.password=VerySecretPassword123",
            )
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"):
            m.validate_diff(["src/app.py"], "+apiKey=VerySecretApiKey123456")
        m.validate_diff(
            ["src/meta.py"],
            "+author = \"Alice\"\n+authentication_required = True",
        )

    def test_mistral_bot_author_or_committer_is_rejected(self):
        base_commit = {
            "sha": "a" * 40,
            "commit": {"message": "change\n\nMaterial-Author: chatgpt"},
        }
        for field in ("author", "committer"):
            item = dict(
                base_commit,
                author={"login": "NTinkicht"},
                committer={"login": "web-flow"},
            )
            item[field] = {"login": "mistral-vibe[bot]"}
            with self.subTest(field=field):
                with mock.patch.object(m, "public_api", return_value=[item]):
                    with self.assertRaisesRegex(
                        ValueError, "MISTRAL_SELF_REVIEW_BLOCKED"
                    ):
                        m.verify_material_authors(
                            "NTinkicht/veritas-atlas",
                            21,
                            "a" * 40,
                            ("chatgpt",),
                        )

    def test_result_pr_requires_real_integer(self):
        value = {
            "version": 1,
            "repo": "NTinkicht/veritas-atlas",
            "pr": True,
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "verdict": "NO_BLOCKING_FINDINGS",
            "summary": "No blocking issue found.",
            "findings": [],
        }
        with self.assertRaises(ValueError):
            m.parse_result(
                json.dumps(value).encode(),
                repo=value["repo"],
                pr=1,
                head=value["head_sha"],
                base=value["base_sha"],
                changed={"src/app.py"},
            )

    def test_terminal_dedupe_requires_matching_run_scoped_proof(self):
        body = (
            "<!-- " + m.EXTERNAL_MARKER
            + " repo=NTinkicht/veritas-atlas pr=21 "
            + "head=" + "a" * 40 + " base=" + "b" * 40
            + " run=123 dispatch=456 verdict=CHANGES_REQUIRED "
            + "result_sha256=" + "c" * 64 + " -->"
        )
        item = {
            "id": 789,
            "html_url": "https://github.com/NTinkicht/OneCompany/issues/130#issuecomment-789",
            "user": {"login": "github-actions[bot]"},
            "body": body,
        }
        run = {
            "id": 123,
            "path": m.EXTERNAL_WORKFLOW_PATH,
            "event": "issue_comment",
            "status": "completed",
            "conclusion": "failure",
        }
        proof = {
            "version": 1,
            "target": {
                "repo": "NTinkicht/veritas-atlas",
                "pr": 21,
                "head_sha": "a" * 40,
                "base_sha": "b" * 40,
            },
            "run_id": 123,
            "dispatch_comment_id": 456,
            "published_comment_id": 789,
            "published_comment_url": item["html_url"],
            "publisher": "github-actions[bot]",
            "verdict": "CHANGES_REQUIRED",
            "result_sha256": "c" * 64,
            "body_sha256": __import__("hashlib").sha256(
                body.encode("utf-8")
            ).hexdigest(),
        }
        with mock.patch.object(m, "onecompany_api", return_value=run):
            with mock.patch.object(m, "_artifact_proof", return_value=proof):
                self.assertTrue(m._trusted_evidence_comment(
                    item,
                    repo="NTinkicht/veritas-atlas",
                    number=21,
                    head="a" * 40,
                    base="b" * 40,
                ))
                bad = dict(proof, result_sha256="d" * 64)
                with mock.patch.object(m, "_artifact_proof", return_value=bad):
                    self.assertFalse(m._trusted_evidence_comment(
                        item,
                        repo="NTinkicht/veritas-atlas",
                        number=21,
                        head="a" * 40,
                        base="b" * 40,
                    ))


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



    def test_activation_workflow_is_pass_only_immutable_and_no_target_write(self):
        workflow = (
            ROOT / ".github/workflows/onecompany-mistral-external-review.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("if: always()", workflow)
        self.assertIn('test "$VERDICT" = "PASS"', workflow)
        self.assertIn(
            "permissions:\n  contents: read\n  issues: write\n  actions: read",
            workflow,
        )
        self.assertNotIn("pull-requests: write", workflow)
        self.assertIn("ref: $" + "{{ github.sha }}", workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', workflow)
        self.assertIn("--filter=blob:none", workflow)
        self.assertIn('merge-base "$TARGET_BASE" "$TARGET_HEAD"', workflow)
        self.assertNotIn('test "$MERGE_BASE" = "$TARGET_BASE"', workflow)
        helper = (ROOT / "scripts/mistral_external_review.py").read_text(encoding="utf-8")
        self.assertIn('"merge-base", base, head', helper)
        self.assertIn('"--name-only", merge_base, head', helper)
        self.assertIn('"merge_base_sha": merge_base', helper)
        self.assertIn("group: onecompany-mistral-external-review", workflow)

    def test_bootstrap_excludes_source_only_external_review_surfaces(self):
        bootstrap = (ROOT / "scripts/bootstrap.py").read_text(encoding="utf-8")
        self.assertIn(
            '".onecompany/selftest/test_mistral_external_review.py"', bootstrap
        )
        self.assertIn('"scripts/mistral_external_review.py"', bootstrap)
        self.assertIn(
            '".github/workflows/onecompany-mistral-external-review.yml"', bootstrap
        )
        self.assertIn('"docs/MISTRAL-EXTERNAL-REVIEW.md"', bootstrap)


    def test_workflow_dispatch_source_must_match_trusted_bot_comment(self):
        body = (
            "@mistral-vibe\nMISTRAL_EXTERNAL_REVIEW_V1\n"
            "repo: NTinkicht/veritas-atlas\npr: 21\n"
            "head_sha: " + "a" * 40 + "\nbase_sha: " + "b" * 40 + "\n"
            "material_authors: chatgpt\n"
            "<!-- ONECOMPANY_L4_AUTO_DISPATCH_V1 run=123 -->\n"
        )
        trusted = {
            "user": {"login": "github-actions[bot]"},
            "body": body,
        }
        env = {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "SOURCE_COMMENT_ID": "789",
        }
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(m, "onecompany_api", return_value=trusted):
            m._validate_dispatch_source(body)

        bad = dict(trusted, body=body + "tampered")
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(m, "onecompany_api", return_value=bad):
            with self.assertRaisesRegex(
                ValueError, "EXTERNAL_REVIEW_SOURCE_COMMENT_UNTRUSTED"
            ):
                m._validate_dispatch_source(body)

    def test_trusted_evidence_accepts_authenticated_workflow_dispatch_run(self):
        item, proof = self._proof()
        run = {
            "id": 123,
            "path": m.EXTERNAL_WORKFLOW_PATH,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
        }
        with mock.patch.object(m, "onecompany_api", return_value=run), \
             mock.patch.object(m, "_artifact_proof", return_value=proof):
            self.assertTrue(m._trusted_evidence_comment(
                item, repo="NTinkicht/veritas-atlas", number=21,
                head="a" * 40, base="b" * 40,
            ))


if __name__ == "__main__":
    unittest.main()
