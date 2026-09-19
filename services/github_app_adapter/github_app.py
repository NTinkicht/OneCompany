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
                or ":" in endpoint or method not in {"GET", "POST", "PATCH"}):
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

    def _installation(self) -> tuple[str, str, int]:
        """Request read-only permissions for exactly one repository."""
        app_jwt = self._jwt()
        app = self._stage_call("app_metadata", "GET", "/app", app_jwt)
        if not isinstance(app, dict) or app.get("id") != self.settings.app_id:
            raise AdapterRefused("github_app_identity_mismatch")
        slug = app.get("slug")
        if not isinstance(slug, str) or not slug:
            raise AdapterRefused("github_app_slug_missing")
        # Resolve the ACTUAL installation bound to the approved repository.
        # The App JWT is the authority; no user-supplied installation ID
        # may select a different account or repository.
        assigned = self._stage_call(
            "repository_installation_lookup", "GET",
            f"/repos/{self.settings.repository}/installation", app_jwt,
        )
        if not isinstance(assigned, dict) or not isinstance(assigned.get("id"), int) or assigned["id"] < 1:
            raise AdapterRefused("github_repository_installation_invalid")
        installation_id = assigned["id"]
        repo_name = self.settings.repository.split("/", 1)[1]
        info = self._stage_call(
            "installation_token", "POST",
            f"/app/installations/{installation_id}/access_tokens",
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
        return token, slug, installation_id

    def identity(self) -> dict:
        token, slug, installation_id = self._installation()
        repo = self._stage_call("repository", "GET", f"/repos/{self.settings.repository}", token)
        if not isinstance(repo, dict) or repo.get("full_name") != self.settings.repository:
            raise AdapterRefused("github_repository_identity_mismatch")
        return {
            "logical_actor": self.settings.actor,
            "authenticated_principal": slug + "[bot]",
            "app_id": self.settings.app_id,
            "installation_id": installation_id,
            "repository": repo["full_name"],
            "mode": "read_only",
            "unattended_write_verified": False,
            "independent_final_gate": False,
            "lease_bound_write_enabled": False,
        }

    def repository_status(self) -> dict:
        token, slug, installation_id = self._installation()
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

    def pull_request_head(self, pr_number: int) -> dict:
        """Discover live PR SHA before requesting the pinned snapshot."""
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or not (1 <= pr_number <= 1000000):
            raise AdapterRefused("positive_pr_number_required")
        token, slug, _ = self._installation()
        item = self._stage_call(
            "pr_head", "GET",
            f"/repos/{self.settings.repository}/pulls/{pr_number}", token,
        )
        if (not isinstance(item, dict) or item.get("number") != pr_number
                or item.get("state") != "open"
                or ((item.get("head") or {}).get("repo") or {}).get("full_name")
                    != self.settings.repository
                or not isinstance((item.get("head") or {}).get("sha"), str)
                or not _SHA.fullmatch(item["head"]["sha"])
                or ((item.get("base") or {}).get("repo") or {}).get("full_name")
                    != self.settings.repository):
            raise AdapterRefused("pr_head_unavailable_or_foreign")
        return {
            "repository": self.settings.repository,
            "pr_number": pr_number,
            "exact_head_sha": item["head"]["sha"],
            "head_branch": item["head"].get("ref"),
            "base_branch": item["base"].get("ref"),
            "authenticated_principal": slug + "[bot]",
            "read_only": True,
        }

    def pull_request_snapshot(self, pr_number: int, exact_head_sha: str) -> dict:
        """Read exactly one existing PR at an explicitly supplied immutable head."""
        if (not isinstance(pr_number, int) or isinstance(pr_number, bool)
                or not (1 <= pr_number <= 1000000)
                or not isinstance(exact_head_sha, str)
                or not _SHA.fullmatch(exact_head_sha)):
            raise AdapterRefused("exact_pr_number_and_head_required")
        token, slug, _ = self._installation()
        doc = self._stage_call(
            "pr_snapshot", "GET",
            f"/repos/{self.settings.repository}/pulls/{pr_number}", token,
        )
        if not isinstance(doc, dict) or doc.get("number") != pr_number:
            raise AdapterRefused("pr_identity_mismatch")
        head = doc.get("head")
        base = doc.get("base")
        if (not isinstance(head, dict) or not isinstance(base, dict)
                or (head.get("repo") or {}).get("full_name") != self.settings.repository
                or head.get("sha") != exact_head_sha
                or (base.get("repo") or {}).get("full_name") != self.settings.repository
                or doc.get("state") != "open"):
            raise AdapterRefused("pr_head_or_repository_changed")
        files = self._stage_call(
            "pr_files", "GET",
            f"/repos/{self.settings.repository}/pulls/{pr_number}/files?per_page=100&page=1",
            token,
        )
        # Never present a truncated change list as complete review material.
        if not isinstance(files, list) or len(files) >= 100:
            raise AdapterRefused("pr_file_list_unbounded_or_incomplete")
        output = []
        for file in files:
            if not isinstance(file, dict) or not isinstance(file.get("filename"), str):
                raise AdapterRefused("pr_file_metadata_invalid")
            output.append({
                "path": file["filename"],
                "status": file.get("status"),
                "additions": file.get("additions"),
                "deletions": file.get("deletions"),
            })
        return {
            "repository": self.settings.repository,
            "pr_number": pr_number,
            "title": str(doc.get("title", ""))[:300],
            "draft": bool(doc.get("draft")),
            "head_sha": exact_head_sha,
            "head_branch": head.get("ref"),
            "base_sha": base.get("sha"),
            "base_branch": base.get("ref"),
            "changed_files": output,
            "authenticated_principal": slug + "[bot]",
            "read_only": True,
            "review_attestation": False,
        }

    def read_source(self, path: str, exact_commit_sha: str,
                    start_line: int, end_line: int) -> dict:
        """Bounded source excerpt from a pinned Git commit; no moving refs."""
        if not isinstance(exact_commit_sha, str) or not _SHA.fullmatch(exact_commit_sha):
            raise AdapterRefused("exact_commit_sha_required")
        if (not isinstance(path, str) or len(path) > 150
                or ".." in path or "//" in path or path.startswith("/")
                or not re.fullmatch(
                    r"(?:services|scripts|tests|agents|patterns|docs|company|examples|overlays)/"
                    r"[A-Za-z0-9_.\-/]+\.(?:py|md|json|yml|yaml|toml|txt|ts|tsx|js|jsx|css|html|sh|ps1)",
                    path,
                )
                or any(part.startswith(".") for part in path.split("/"))):
            raise AdapterRefused("source_path_not_allowlisted")
        if (not isinstance(start_line, int) or isinstance(start_line, bool)
                or not isinstance(end_line, int) or isinstance(end_line, bool)
                or start_line < 1 or end_line < start_line
                or end_line - start_line > 159):
            raise AdapterRefused("source_line_range_invalid")
        token, _, _ = self._installation()
        result = self._stage_call(
            "source", "GET",
            f"/repos/{self.settings.repository}/contents/"
            + urllib.parse.quote(path, safe="/") + "?ref=" + exact_commit_sha,
            token,
        )
        if not isinstance(result, dict) or result.get("type") != "file":
            raise AdapterRefused("source_not_file")
        try:
            if result.get("encoding") != "base64" or not isinstance(result.get("content"), str):
                raise ValueError("invalid_source_encoding")
            content = base64.b64decode(
                re.sub(r"[ \t\r\n]", "", result["content"]), validate=True,
            )
            if len(content) > 96_000:
                raise AdapterRefused("source_exceeds_limit")
            lines = content.decode("utf-8").splitlines()
        except (ValueError, UnicodeError, KeyError) as exc:
            raise AdapterRefused("source_content_unavailable") from exc
        excerpt = "\n".join(lines[start_line - 1:end_line])
        if len(excerpt.encode("utf-8")) > 30_000:
            raise AdapterRefused("source_excerpt_exceeds_limit")
        return {
            "repository": self.settings.repository,
            "path": path,
            "exact_commit_sha": exact_commit_sha,
            "start_line": start_line,
            "end_line": min(end_line, len(lines)),
            "total_lines": len(lines),
            "content": excerpt,
            "read_only": True,
        }

    def read_document(self, path: str, ref: str) -> dict:
        """Read allowlisted Markdown only at an immutable SHA."""
        if not _SHA.fullmatch(ref):
            raise AdapterRefused("exact_commit_sha_required")
        if (not _FILE.fullmatch(path) or ".." in path
                or "//" in path or len(path) > 160):
            raise AdapterRefused("document_path_not_allowlisted")
        token, _, _ = self._installation()
        live_main = self._stage_call(
            "main_head", "GET",
            f"/repos/{self.settings.repository}/git/ref/heads/main", token,
        )
        live_main_sha = (live_main.get("object") or {}).get("sha") if isinstance(live_main, dict) else None
        if live_main_sha != ref:
            raise AdapterRefused("approved_main_head_sha_required")
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
