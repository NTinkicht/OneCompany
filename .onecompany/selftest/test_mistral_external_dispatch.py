import os
import time
import unittest
from unittest import mock
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import mistral_external_dispatch as d


class ExternalReviewAutoDispatchTests(unittest.TestCase):
    def test_dispatch_body_is_exact_head_and_run_bound(self):
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "12345"}, clear=False):
            body = d.dispatch_body(
                "NTinkicht/veritas-atlas", 22, "a" * 40, "b" * 40,
                ("chatgpt", "github-ntinkicht"),
            )
        self.assertIn("MISTRAL_EXTERNAL_REVIEW_V1", body)
        self.assertIn("repo: NTinkicht/veritas-atlas", body)
        self.assertIn("pr: 22", body)
        self.assertIn("head_sha: " + "a" * 40, body)
        self.assertIn("base_sha: " + "b" * 40, body)
        self.assertIn("material_authors: chatgpt,github-ntinkicht", body)
        self.assertIn("ONECOMPANY_L4_AUTO_DISPATCH_V1 run=12345", body)

    def test_recent_auto_dispatch_suppresses_duplicate_but_expires(self):
        now = int(time.time())
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 60))
        body = (
            "@mistral-vibe\nMISTRAL_EXTERNAL_REVIEW_V1\n"
            "repo: NTinkicht/veritas-atlas\npr: 22\n"
            "head_sha: " + "a" * 40 + "\nbase_sha: " + "b" * 40 + "\n"
            "material_authors: chatgpt\n"
            "<!-- ONECOMPANY_L4_AUTO_DISPATCH_V1 run=123 -->\n"
        )
        comments = [{
            "user": {"login": "github-actions[bot]"},
            "body": body,
            "created_at": stamp,
        }]
        self.assertTrue(d.terminal_or_pending(
            comments, repo="NTinkicht/veritas-atlas", number=22,
            head="a" * 40, base="b" * 40, now=now,
        ))
        self.assertFalse(d.terminal_or_pending(
            comments, repo="NTinkicht/veritas-atlas", number=22,
            head="a" * 40, base="b" * 40,
            now=now + d.PENDING_TTL_SECONDS + 61,
        ))

    def test_terminal_evidence_suppresses_future_dispatch(self):
        comments = [{
            "user": {"login": "github-actions[bot]"},
            "created_at": "2026-09-27T00:00:00Z",
            "body": (
                "<!-- ONECOMPANY_EXTERNAL_MISTRAL_REVIEW_V1 "
                "repo=NTinkicht/veritas-atlas pr=22 "
                "head=" + "a" * 40 + " base=" + "b" * 40 + " "
                "run=1 dispatch=2 verdict=PASS result_sha256=" + "c" * 64 + " -->"
            ),
        }]
        self.assertTrue(d.terminal_or_pending(
            comments, repo="NTinkicht/veritas-atlas", number=22,
            head="a" * 40, base="b" * 40, now=int(time.time()),
        ))

    def test_material_authors_reject_mistral_self_review(self):
        commits = [{
            "sha": "a" * 40,
            "author": {"login": "mistral-vibe"},
            "committer": {"login": "web-flow"},
            "commit": {
                "message": "change\n\nMaterial-Author: chatgpt",
                "author": {"name": "Alice", "email": "alice@example.com"},
                "committer": {"name": "GitHub", "email": "noreply@github.com"},
            },
        }]
        with mock.patch.object(d, "request_json", return_value=commits):
            with self.assertRaisesRegex(ValueError, "MISTRAL_SELF_REVIEW_BLOCKED"):
                d.material_authors("NTinkicht/veritas-atlas", 22, "a" * 40)

    def test_emergency_stop_prevents_any_dispatch_work(self):
        with mock.patch.object(d, "emergency_stop_active", return_value=True), \
             mock.patch.object(d, "recent_bus_comments") as comments, \
             mock.patch.object(d, "same_repo_open_prs") as pulls, \
             mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": d.HOST_REPO}, clear=False):
            self.assertEqual(d.main(), 0)
            comments.assert_not_called()
            pulls.assert_not_called()

    def test_complete_bounded_wake_bus_paginates_to_newest(self):
        pages = {
            1: [{"id": i} for i in range(100)],
            2: [{"id": i} for i in range(100, 150)],
        }
        def request(route, **_kwargs):
            page = int(route.rsplit("page=", 1)[1])
            return pages[page]
        with mock.patch.object(d, "request_json", side_effect=request):
            comments = d.recent_bus_comments()
        self.assertEqual(len(comments), 150)
        self.assertEqual(comments[-1]["id"], 149)

    def test_wake_bus_fails_closed_when_history_bound_is_exhausted(self):
        full = [{"id": i} for i in range(100)]
        with mock.patch.object(d, "request_json", return_value=full):
            with self.assertRaisesRegex(ValueError, "WAKE_BUS_HISTORY_OVER_LIMIT"):
                d.recent_bus_comments()

    def test_explicit_workflow_dispatch_carries_comment_provenance(self):
        calls = []
        def request(route, **kwargs):
            calls.append((route, kwargs))
            return {}
        body = "MISTRAL_EXTERNAL_REVIEW_V1\n"
        with mock.patch.object(d, "request_json", side_effect=request):
            d.dispatch_review_workflow(body=body, source_comment_id=789)
        route, kwargs = calls[0]
        self.assertIn(
            "actions/workflows/onecompany-mistral-external-review.yml/dispatches",
            route,
        )
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["body"]["ref"], "main")
        self.assertEqual(kwargs["body"]["inputs"]["dispatch_body"], body)
        self.assertEqual(kwargs["body"]["inputs"]["source_comment_id"], "789")

    def test_workflows_bind_auto_dispatch_to_trusted_main(self):
        dispatcher = (
            ROOT / ".github/workflows/onecompany-mistral-external-dispatch.yml"
        ).read_text(encoding="utf-8")
        reviewer = (
            ROOT / ".github/workflows/onecompany-mistral-external-review.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("schedule:", dispatcher)
        self.assertIn("issues: write", dispatcher)
        self.assertIn("actions: write", dispatcher)
        self.assertIn("ref: $" + "{{ github.sha }}", dispatcher)
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', dispatcher)
        self.assertIn("workflow_dispatch:", reviewer)
        self.assertIn("inputs.dispatch_body", reviewer)
        self.assertIn("inputs.source_comment_id", reviewer)
        self.assertIn("ONECOMPANY_L4_AUTO_DISPATCH_V1", reviewer)


if __name__ == "__main__":
    unittest.main()
