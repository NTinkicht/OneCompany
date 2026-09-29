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
            "id": 789,
            "user": {"login": "github-actions[bot]"},
            "body": body,
            "created_at": stamp,
        }, {
            "id": 790,
            "user": {"login": "github-actions[bot]"},
            "body": (
                "<!-- ONECOMPANY_L4_REVIEW_HANDOFF_V1 source=789 "
                "repo=NTinkicht/veritas-atlas pr=22 "
                "head=" + "a" * 40 + " base=" + "b" * 40 + " -->"
            ),
            "created_at": stamp,
        }]
        self.assertTrue(d.terminal_or_pending(
            comments, repo="NTinkicht/veritas-atlas", number=22,
            head="a" * 40, base="b" * 40, authors=("chatgpt",), now=now,
        ))
        self.assertFalse(d.terminal_or_pending(
            comments, repo="NTinkicht/veritas-atlas", number=22,
            head="a" * 40, base="b" * 40, authors=("chatgpt",),
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
        with mock.patch.object(
            d.review_service, "_trusted_evidence_comment", return_value=True
        ):
            self.assertTrue(d.terminal_or_pending(
                comments, repo="NTinkicht/veritas-atlas", number=22,
                head="a" * 40, base="b" * 40,
                authors=("chatgpt",), now=int(time.time()),
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

    def test_repository_dispatch_carries_comment_provenance(self):
        calls = []
        def request(route, **kwargs):
            calls.append((route, kwargs))
            return {}
        body = "MISTRAL_EXTERNAL_REVIEW_V1\n"
        with mock.patch.object(d, "request_json", side_effect=request):
            d.dispatch_review_workflow(
                body=body, source_comment_id=789,
                target_key="veritas-atlas-22-" + "a" * 40 + "-" + "b" * 40,
            )
        route, kwargs = calls[0]
        self.assertIn(
            "repos/NTinkicht/OneCompany/dispatches",
            route,
        )
        self.assertEqual(kwargs["method"], "POST")

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
        self.assertIn("repository_dispatch:", reviewer)
        self.assertIn("github.event.client_payload.dispatch_body", reviewer)
        self.assertIn("github.event.client_payload.source_comment_id", reviewer)
        self.assertIn(
            "github.event.client_payload.target_key",
            reviewer,
        )
        self.assertIn("ONECOMPANY_L4_AUTO_DISPATCH_V1", reviewer)

    def test_retry_attempts_are_capped(self):
        now = int(time.time())
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - d.PENDING_TTL_SECONDS - 100))
        comments = []
        for run in range(d.MAX_REVIEW_ATTEMPTS_PER_TARGET):
            source_id = 1000 + run
            comments.append({
                "id": source_id,
                "user": {"login": "github-actions[bot]"},
                "created_at": old,
                "body": (
                    "@mistral-vibe\nMISTRAL_EXTERNAL_REVIEW_V1\n"
                    "repo: NTinkicht/veritas-atlas\npr: 22\n"
                    "head_sha: " + "a" * 40 + "\nbase_sha: " + "b" * 40 + "\n"
                    "material_authors: chatgpt\n"
                    f"<!-- ONECOMPANY_L4_AUTO_DISPATCH_V1 run={run + 1} -->\n"
                ),
            })
            comments.append({
                "id": 2000 + run,
                "user": {"login": "github-actions[bot]"},
                "created_at": old,
                "body": (
                    f"<!-- ONECOMPANY_L4_REVIEW_HANDOFF_V1 source={source_id} "
                    "repo=NTinkicht/veritas-atlas pr=22 "
                    "head=" + "a" * 40 + " base=" + "b" * 40 + " -->"
                ),
            })
        self.assertTrue(d.terminal_or_pending(
            comments, repo="NTinkicht/veritas-atlas", number=22,
            head="a" * 40, base="b" * 40, authors=("chatgpt",), now=now,
        ))

    def test_live_emergency_stop_reads_protected_main(self):
        payload = {
            "encoding": "base64",
            "content": __import__("base64").b64encode(
                b'{"safety":{"emergency_stop":true}}'
            ).decode("ascii"),
        }
        with mock.patch.object(d, "request_json", return_value=payload) as request:
            self.assertTrue(d.emergency_stop_active())
        self.assertIn(
            "contents/.onecompany/config.json?ref=main",
            request.call_args.args[0],
        )

    def test_failed_handoff_comment_does_not_consume_retry(self):
        now = int(time.time())
        comments = [{
            "id": 789,
            "user": {"login": "github-actions[bot]"},
            "created_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 60)
            ),
            "body": (
                "@mistral-vibe\nMISTRAL_EXTERNAL_REVIEW_V1\n"
                "repo: NTinkicht/veritas-atlas\npr: 22\n"
                "head_sha: " + "a" * 40 + "\nbase_sha: " + "b" * 40 + "\n"
                "material_authors: chatgpt\n"
                "<!-- ONECOMPANY_L4_AUTO_DISPATCH_V1 run=123 -->\n"
            ),
        }]
        self.assertFalse(d.terminal_or_pending(
            comments, repo="NTinkicht/veritas-atlas", number=22,
            head="a" * 40, base="b" * 40, authors=("chatgpt",), now=now,
        ))

    def test_material_authors_paginates(self):
        first = [{
            "sha": ("%040x" % i),
            "author": {"login": "NTinkicht"},
            "committer": {"login": "web-flow"},
            "commit": {"message": "x\n\nMaterial-Author: chatgpt"},
        } for i in range(100)]
        second = [{
            "sha": "a" * 40,
            "author": {"login": "NTinkicht"},
            "committer": {"login": "web-flow"},
            "commit": {"message": "x\n\nMaterial-Author: chatgpt"},
        }]
        def request(route, **_kwargs):
            page = int(route.rsplit("page=", 1)[1])
            return first if page == 1 else second
        with mock.patch.object(d, "request_json", side_effect=request):
            self.assertEqual(
                d.material_authors("NTinkicht/veritas-atlas", 22, "a" * 40),
                ("chatgpt",),
            )

    def test_review_capability_reads_live_main_controls(self):
        import base64, json
        payloads = {
            ".onecompany/actors.json": {"actors": [{
                "id": "mistral-vibe", "enabled": True, "configured": True,
                "capabilities": ["code_review"],
            }]},
            ".onecompany/readiness.json": {"actors": [{
                "actor_id": "mistral-vibe", "setup_state": "ready",
                "unattended": {"configured": True, "verified": True},
                "temporarily_unavailable_capabilities": [],
                "verified_capabilities": ["code_review"],
                "repository_access": {"review": True},
            }]},
            ".onecompany/dispatch.json": {"actors": [{
                "actor_id": "mistral-vibe", "mechanisms": [{
                    "id": "vibe-exact-head-review", "configured": True,
                    "unattended": True, "capabilities": ["code_review"],
                }],
            }]},
        }
        def request(route, **_kwargs):
            path = route.split("/contents/", 1)[1].split("?ref=main", 1)[0]
            raw = json.dumps(payloads[path]).encode()
            return {"encoding": "base64", "content": base64.b64encode(raw).decode()}
        with mock.patch.object(d, "request_json", side_effect=request):
            self.assertTrue(d.review_capability_approved())

    def test_handoff_receipt_is_separate_from_authenticated_source(self):
        body = (
            "@mistral-vibe\nMISTRAL_EXTERNAL_REVIEW_V1\n"
            "repo: NTinkicht/veritas-atlas\npr: 22\n"
            "head_sha: " + "a" * 40 + "\nbase_sha: " + "b" * 40 + "\n"
            "material_authors: chatgpt\n"
            "<!-- ONECOMPANY_L4_AUTO_DISPATCH_V1 run=123 -->\n"
        )
        calls = []
        responses = [
            {"id": 789, "user": {"login": "github-actions[bot]"}, "body": body},
            {},
            {"id": 790, "user": {"login": "github-actions[bot]"},
             "body": (
                 "<!-- ONECOMPANY_L4_REVIEW_HANDOFF_V1 source=789 "
                 "repo=NTinkicht/veritas-atlas pr=22 "
                 "head=" + "a" * 40 + " base=" + "b" * 40 + " -->"
             )},
        ]
        def request(route, **kwargs):
            calls.append((route, kwargs))
            return responses.pop(0)
        pr = {
            "number": 22, "draft": False, "state": "open",
            "head": {"sha": "a" * 40, "repo": {"full_name": "NTinkicht/veritas-atlas"}},
            "base": {"sha": "b" * 40, "ref": "main",
                     "repo": {"full_name": "NTinkicht/veritas-atlas"}},
        }
        with mock.patch.dict(os.environ, {
            "GITHUB_REPOSITORY": d.HOST_REPO, "GITHUB_RUN_ID": "123"
        }, clear=False), \
             mock.patch.object(d, "emergency_stop_active", return_value=False), \
             mock.patch.object(d, "review_capability_approved", return_value=True), \
             mock.patch.object(d, "recent_bus_comments", return_value=[]), \
             mock.patch.object(d, "same_repo_open_prs", side_effect=[[pr], []]), \
             mock.patch.object(d, "material_authors", return_value=("chatgpt",)), \
             mock.patch.object(d, "request_json", side_effect=request):
            self.assertEqual(d.main(), 0)
        self.assertEqual(calls[0][1]["body"]["body"], body)
        self.assertEqual(calls[1][1]["body"]["client_payload"]["dispatch_body"], body)
        self.assertNotEqual(calls[2][1]["body"]["body"], body)


if __name__ == "__main__":
    unittest.main()
