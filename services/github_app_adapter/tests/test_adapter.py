"""Offline OneCompany App adapter tests: no paid provider, network, or keys."""
from __future__ import annotations
import asyncio
import base64
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "services" / "github_app_adapter"
sys.path.insert(0, str(SERVICE))

from auth import BearerGuard
from github_app import AdapterRefused, AppClient
from settings import Settings

class FakeClient(AppClient):
    def __init__(self, settings):
        super().__init__(settings)
        self.calls = []

    def _jwt(self):
        return "test-jwt"

    def _call(self, method, path, token, payload=None):
        self.calls.append((method, path, payload))
        if path == "/app":
            return {"id": self.settings.app_id, "slug": "onecompany-grok-worker"}
        if path == "/app/installations/34":
            return {"id": 34}
        if path == "/repos/owner/disposable/installation":
            return {"id": 34}
        if path.endswith("/access_tokens"):
            return {
                "token": "z" * 40,
                "permissions": {"contents": "read", "pull_requests": "read"},
                "repository_selection": "selected",
                "repositories": [{"full_name": self.settings.repository}],
            }
        if path == "/repos/owner/disposable":
            return {"full_name": self.settings.repository,
                    "default_branch": "main", "private": False}
        if "/contents/" in path:
            return {"type": "file", "encoding": "base64",
                    "content": base64.b64encode(b"# Hello\n").decode()}
        raise AssertionError((method, path))

def settings(**overrides):
    data = {
        "enabled": True, "connector_secret": "x" * 42,
        "app_id": 12, "installation_id": 34,
        "private_key_path": Path("/nonexistent"),
        "repository": "owner/disposable",
        "public_host": "onecompany-github-adapter.onrender.com",
    }
    data.update(overrides)
    return Settings(**data)

class TestGrokAppAdapter(unittest.TestCase):
    """Negative cases are essential because source still operates at L1."""

    def test_logical_and_app_principals_differ(self):
        result = FakeClient(settings()).identity()
        self.assertEqual(result["logical_actor"], "grok-4-6-interactive")
        self.assertEqual(
            result["authenticated_principal"], "onecompany-grok-worker[bot]"
        )
        self.assertFalse(result["independent_final_gate"])
        self.assertFalse(result["unattended_write_verified"])
        self.assertFalse(result["lease_bound_write_enabled"])

    def test_upstream_errors_identify_phase_without_leaking_credentials(self):
        class RejectApp(FakeClient):
            def _call(self, method, path, token, payload=None):
                if path == "/app":
                    raise AdapterRefused("github_http_status_404")
                return super()._call(method, path, token, payload)
        class RejectRepositoryInstallation(FakeClient):
            def _call(self, method, path, token, payload=None):
                if path == "/repos/owner/disposable/installation":
                    raise AdapterRefused("github_http_status_404")
                return super()._call(method, path, token, payload)
        class RejectInstallation(FakeClient):
            def _call(self, method, path, token, payload=None):
                if path.endswith("/access_tokens"):
                    raise AdapterRefused("github_http_status_404")
                return super()._call(method, path, token, payload)
        class RejectRepository(FakeClient):
            def _call(self, method, path, token, payload=None):
                if path == "/repos/owner/disposable":
                    raise AdapterRefused("github_http_status_404")
                return super()._call(method, path, token, payload)
        for cls, phase in (
            (RejectApp, "app_metadata"),
            (RejectRepositoryInstallation, "repository_installation_lookup"),
            (RejectInstallation, "installation_token"),
            (RejectRepository, "repository"),
        ):
            with self.subTest(phase=phase):
                with self.assertRaisesRegex(
                    AdapterRefused,
                    f"github_{phase}_github_http_status_404",
                ):
                    cls(settings()).identity()

    def test_installation_id_is_discovered_without_manual_setting(self):
        client = FakeClient(settings(installation_id=999))
        result = client.identity()
        self.assertEqual(result["installation_id"], 34)
        self.assertEqual(client.calls[2][1], "/app/installations/34/access_tokens")
        self.assertEqual(result["repository"], "owner/disposable")

    def test_installation_token_scope_never_expands(self):
        client = FakeClient(settings())
        client.identity()
        self.assertEqual(client.calls[2][2], {
            "repositories": ["disposable"],
            "permissions": {"contents": "read", "pull_requests": "read"},
        })
        class ForeignClient(FakeClient):
            def _call(self, method, path, token, payload=None):
                answer = super()._call(method, path, token, payload)
                if path.endswith("/access_tokens"):
                    answer["repositories"] = [{"full_name": "owner/other"}]
                return answer
        with self.assertRaisesRegex(AdapterRefused, "scope_unverified"):
            ForeignClient(settings()).identity()

    def test_pr_snapshot_is_exact_head_readonly(self):
        class PRClient(FakeClient):
            def _call(self, method, path, token, payload=None):
                if path == "/repos/owner/disposable/pulls/102":
                    return {
                        "number": 102, "state": "open", "title": "Testing",
                        "draft": False,
                        "head": {"sha": "a" * 40, "ref": "wu-test",
                                 "repo": {"full_name": "owner/disposable"}},
                        "base": {"sha": "b" * 40, "ref": "main",
                                 "repo": {"full_name": "owner/disposable"}},
                    }
                if path.startswith("/repos/owner/disposable/pulls/102/files?"):
                    return [{"filename": "scripts/test.py", "status": "modified",
                             "additions": 2, "deletions": 1}]
                return super()._call(method, path, token, payload)
        client = PRClient(settings())
        with self.assertRaisesRegex(AdapterRefused, "head_required"):
            client.pull_request_snapshot(102, "main")
        with self.assertRaisesRegex(AdapterRefused, "head_or_repository_changed"):
            client.pull_request_snapshot(102, "c" * 40)
        head = client.pull_request_head(102)
        self.assertEqual(head["exact_head_sha"], "a" * 40)
        self.assertTrue(head["read_only"])
        result = client.pull_request_snapshot(102, "a" * 40)
        self.assertEqual(result["head_branch"], "wu-test")
        self.assertEqual(result["authenticated_principal"], "onecompany-grok-worker[bot]")
        self.assertEqual(result["changed_files"][0]["path"], "scripts/test.py")
        self.assertFalse(result["review_attestation"])

    def test_source_excerpt_requires_safe_path_and_pinned_sha(self):
        client = FakeClient(settings())
        for path in (".onecompany/ledger.json", "../secret.txt",
                     "services/.env", "scripts/secret.pem",
                     "scripts/test.py/../../config.py"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(AdapterRefused, "source_path_not_allowlisted"):
                    client.read_source(path, "a" * 40, 1, 2)
        with self.assertRaisesRegex(AdapterRefused, "exact_commit"):
            client.read_source("scripts/lease.py", "main", 1, 5)
        with self.assertRaisesRegex(AdapterRefused, "source_line_range"):
            client.read_source("scripts/lease.py", "a" * 40, 1, 500)
        result = client.read_source("scripts/lease.py", "a" * 40, 1, 2)
        self.assertEqual(result["content"], "# Hello")
        self.assertEqual(result["total_lines"], 1)

    def test_reject_mutable_ref_and_unauthorized_document_paths(self):
        client = FakeClient(settings())
        for path, ref in [
            ("README.md", "main"),
            ("../secret.pem", "a" * 40),
            (".github/workflows/work.yml", "a" * 40),
        ]:
            with self.subTest(path=path, ref=ref):
                with self.assertRaises(AdapterRefused):
                    client.read_document(path, ref)
        self.assertEqual(client.calls, [])
        self.assertEqual(
            client.read_document("docs/START.md", "a" * 40)["content"],
            "# Hello\n",
        )

    def test_bearer_guard_refuses_missing_wrong_or_duplicate_tokens(self):
        seen = []
        async def app(scope, receive, send):
            seen.append(True)
        guard = BearerGuard(app, settings())
        async def request(headers, path="/mcp"):
            result = []
            async def send(event):
                result.append(event)
            await guard({"type": "http", "path": path,
                         "headers": headers}, None, send)
            return result
        self.assertEqual(asyncio.run(request([]))[0]["status"], 401)
        self.assertEqual(
            asyncio.run(request([(b"authorization", b"Bearer wrong")]))[0]["status"],
            401,
        )
        duplicates = [(b"authorization", b"Bearer " + b"x"*42)] * 2
        self.assertEqual(asyncio.run(request(duplicates))[0]["status"], 401)
        self.assertFalse(seen)
        asyncio.run(request([(b"authorization", b"Bearer " + b"x"*42)]))
        self.assertEqual(seen, [True])
        asyncio.run(request([], "/health/live"))
        self.assertEqual(seen, [True, True])

    def test_adapter_is_sealed_without_activation(self):
        visited = []
        async def app(scope, receive, send):
            visited.append(True)
        guard = BearerGuard(app, settings(enabled=False))
        async def request():
            output = []
            async def send(event):
                output.append(event)
            await guard({"type": "http", "path": "/mcp",
                         "headers": []}, None, send)
            return output
        self.assertEqual(asyncio.run(request())[0]["status"], 503)
        self.assertFalse(visited)

    def test_key_and_repository_must_be_explicit_and_valid(self):
        self.assertFalse(settings().github_ready())
        self.assertFalse(settings(connector_secret="short").auth_ready())
        with tempfile.TemporaryDirectory() as root:
            key = Path(root) / "github-app.pem"
            key.write_text("test-only" * 40)
            self.assertTrue(settings(private_key_path=key).github_ready())
            self.assertFalse(settings(
                private_key_path=key, repository="../other"
            ).github_ready())

if __name__ == "__main__":
    unittest.main()
