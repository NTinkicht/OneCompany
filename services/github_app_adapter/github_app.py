"""Read-only GitHub App client, scoped to one owner-approved repository.

No user-provided API URL, HTTP method, Git ref mutation, PR merge, or GitHub
installation token is exposed through an MCP tool.
"""
from __future__ import annotations
import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any
import jwt
from settings import Settings

_SHA = re.compile(r"^[0-9a-f]{40}$")
_FILE = re.compile(r"^(?:README\.md|AGENTS\.md|docs/[A-Za-z0-9_.\-/]+\.md)$")

class AdapterRefused(RuntimeError):
    """Sanitized refusal without raw provider responses, credentials or tokens."""

@dataclass
class AppClient:
    settings: Settings

    def _call(self, method: str, endpoint: str, auth_token: str,
              payload: dict | None = None) -> Any:
        """Fixed GitHub host, strict response bound, sanitized transport errors."""
        if (not endpoint.startswith("/") or "//" in endpoint
                or ":" in endpoint or method not in {"GET", "POST"}):
            raise AdapterRefused("invalid_github_endpoint")
        request = urllib.request.Request(
            "https://api.github.com" + endpoint,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            method=method,
            headers={
                "Authorization": "Bearer " + auth_token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "OneCompany-GitHub-App-Adapter",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read(300_001)
            if len(raw) > 300_000:
                raise AdapterRefused("github_payload_exceeds_limit")
            result = json.loads(raw)
            if not isinstance(result, (dict, list)):
                raise AdapterRefused("github_payload_invalid")
            return result
        except urllib.error.HTTPError as exc:
            raise AdapterRefused(f"github_http_status_{exc.code}") from None
        except (OSError, ValueError) as exc:
            raise AdapterRefused("github_request_unavailable") from exc

    def _stage_call(self, stage: str, method: str, endpoint: str,
                    token: str, payload: dict | None = None) -> Any:
        """Return a safe, actionable phase on upstream failures, never a token."""
        try:
            return self._call(method, endpoint, token, payload)
        except AdapterRefused as exc:
            # The provider response body and request credentials remain private.
            raise AdapterRefused(f"github_{stage}_{exc}") from None

    def _jwt(self) -> str:
        if not self.settings.github_ready():
            raise AdapterRefused("github_app_not_configured")
        try:
            private_key = self.settings.private_key_path.read_bytes()
            now = int(time.time())
            return jwt.encode(
                {"iat": now - 60, "exp": now + 480,
                 "iss": str(self.settings.app_id)},
                private_key, algorithm="RS256",
            )
        except Exception as exc:
            raise AdapterRefused("github_app_key_invalid") from exc

    def _installation(self) -> tuple[str, str]:
        """Request read-only permissions for exactly one repository."""
        app_jwt = self._jwt()
        app = self._stage_call("app_metadata", "GET", "/app", app_jwt)
        if not isinstance(app, dict) or app.get("id") != self.settings.app_id:
            raise AdapterRefused("github_app_identity_mismatch")
        slug = app.get("slug")
        if not isinstance(slug, str) or not slug:
            raise AdapterRefused("github_app_slug_missing")
        # Disambiguate a wrong Installation ID from an App not installed on
        # this particular repository. Both can otherwise surface as 404 when
        # POSTing an installation-token request.
        installation = self._stage_call(
            "installation_lookup", "GET",
            f"/app/installations/{self.settings.installation_id}", app_jwt,
        )
        if not isinstance(installation, dict) or (
            installation.get("id") != self.settings.installation_id
        ):
            raise AdapterRefused("github_installation_id_mismatch")
        assigned = self._stage_call(
            "repository_installation_lookup", "GET",
            f"/repos/{self.settings.repository}/installation", app_jwt,
        )
        if not isinstance(assigned, dict) or (
            assigned.get("id") != self.settings.installation_id
        ):
            raise AdapterRefused("github_repository_installation_id_mismatch")
        repo_name = self.settings.repository.split("/", 1)[1]
        info = self._stage_call(
            "installation_token", "POST",
            f"/app/installations/{self.settings.installation_id}/access_tokens",
            app_jwt,
            {"repositories": [repo_name],
             "permissions": {"contents": "read", "pull_requests": "read"}},
        )
        if not isinstance(info, dict):
            raise AdapterRefused("github_installation_token_invalid")
        token = info.get("token")
        permissions = info.get("permissions", {})
        repos = info.get("repositories", [])
        if (
            not isinstance(token, str) or len(token) < 20
            or info.get("repository_selection") != "selected"
            or not isinstance(permissions, dict)
            or permissions.get("contents") != "read"
            or permissions.get("pull_requests") != "read"
            or not isinstance(repos, list) or len(repos) != 1
            or not isinstance(repos[0], dict)
            or repos[0].get("full_name") != self.settings.repository
        ):
            raise AdapterRefused("github_installation_scope_unverified")
        return token, slug

    def identity(self) -> dict:
        token, slug = self._installation()
        repo = self._stage_call("repository", "GET", f"/repos/{self.settings.repository}", token)
        if not isinstance(repo, dict) or repo.get("full_name") != self.settings.repository:
            raise AdapterRefused("github_repository_identity_mismatch")
        return {
            "logical_actor": self.settings.actor,
            "authenticated_principal": slug + "[bot]",
            "app_id": self.settings.app_id,
            "installation_id": self.settings.installation_id,
            "repository": repo["full_name"],
            "mode": "read_only",
            "unattended_write_verified": False,
            "independent_final_gate": False,
            "lease_bound_write_enabled": False,
        }

    def repository_status(self) -> dict:
        token, slug = self._installation()
        repo = self._call("GET", f"/repos/{self.settings.repository}", token)
        if not isinstance(repo, dict) or repo.get("full_name") != self.settings.repository:
            raise AdapterRefused("github_repository_identity_mismatch")
        return {
            "repository": repo["full_name"],
            "default_branch": repo.get("default_branch"),
            "private": repo.get("private"),
            "authenticated_principal": slug + "[bot]",
            "logical_actor": self.settings.actor,
            "write_enabled": False,
        }

    def read_document(self, path: str, ref: str) -> dict:
        """Read allowlisted Markdown only at an immutable SHA."""
        if not _SHA.fullmatch(ref):
            raise AdapterRefused("exact_commit_sha_required")
        if (not _FILE.fullmatch(path) or ".." in path
                or "//" in path or len(path) > 160):
            raise AdapterRefused("document_path_not_allowlisted")
        token, _ = self._installation()
        endpoint = (
            f"/repos/{self.settings.repository}/contents/"
            + urllib.parse.quote(path, safe="/") + "?ref=" + ref
        )
        result = self._stage_call("document", "GET", endpoint, token)
        if not isinstance(result, dict) or result.get("type") != "file":
            raise AdapterRefused("document_not_file")
        try:
            encoded = result["content"]
            if result.get("encoding") != "base64" or not isinstance(encoded, str):
                raise ValueError("invalid_encoding")
            normalized = re.sub(r"[ \t\r\n]", "", encoded)
            content = base64.b64decode(normalized, validate=True)
            if len(content) > 30_000:
                raise AdapterRefused("document_exceeds_limit")
            text = content.decode("utf-8")
        except (KeyError, ValueError, UnicodeError) as exc:
            raise AdapterRefused("document_content_unavailable") from exc
        return {
            "repository": self.settings.repository, "path": path,
            "ref": ref, "content": text,
        }
