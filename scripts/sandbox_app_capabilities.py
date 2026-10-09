#!/usr/bin/env python3
"""GitHub App sandbox write qualification for Claude L5 V2 Phase 1.

This is NOT the production controller. It exercises a scoped installation
token and an actual git checkout without giving an LLM credentials or
treating a read-only capability check as successful write qualification.
Only repositories explicitly named *-l5-sandbox are eligible for mutation.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MANAGED = frozenset({
    "ntinkicht/onecompany", "ntinkicht/tabibi", "ntinkicht/veritas-atlas",
})
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
WRITE_CLASSES = (
    "push", "create_pr", "comment", "request_review", "mark_ready",
    "resolve_thread", "rerun_job", "update_branch", "merge",
)
GRAPH_PR_FRAGMENT = "... on PullRequest {number isDraft repository{nameWithOwner}}"
GRAPH_THREAD_FRAGMENT = (
    "... on PullRequestReviewThread {isResolved pullRequest{number repository{nameWithOwner}}}"
)
GRAPH_READY_MUTATION = (
    "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{id isDraft}}}"
)
GRAPH_RESOLVE_MUTATION = (
    "mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{id isResolved}}}"
)
GRAPH_QUERIES = frozenset({
    "query($id:ID!){node(id:$id){" + GRAPH_PR_FRAGMENT + "}}",
    "query($id:ID!){node(id:$id){" + GRAPH_THREAD_FRAGMENT + "}}",
})


class CapabilityBlocked(RuntimeError):
    """A preflight or remote capability failure, never a transient WAIT."""


def require_sandbox(repo: str) -> str:
    """Refuse all production repositories and ambiguous sandbox names."""
    if not isinstance(repo, str) or not REPOSITORY.fullmatch(repo):
        raise CapabilityBlocked("SANDBOX_REPOSITORY_INVALID")
    if repo.lower() in MANAGED or not repo.lower().split("/")[1].endswith("-l5-sandbox"):
        raise CapabilityBlocked("SANDBOX_ONLY")
    return repo


def require_sha(value: str) -> str:
    if not isinstance(value, str) or not SHA40.fullmatch(value):
        raise CapabilityBlocked("EXPECTED_SHA_INVALID")
    return value


class SandboxApp:
    """Low-level GitHub App installation client restricted to one sandbox."""

    def __init__(self, repo: str, token: str):
        self.repo = require_sandbox(repo)
        if not isinstance(token, str) or len(token.strip()) < 10:
            raise CapabilityBlocked("BLOCK_PERMISSION:APP_TOKEN_MISSING")
        self._token = token.strip()
        self._scope_verified = False
        self._default_branch: str | None = None
        self._authorized_graph_nodes: dict[str, str] = {}
        # One-time, exact-commit authorization produced ONLY by successful
        # sandbox App git push and verified through GitHub branch readback.
        self._pr_push_authorizations: dict[str, str] = {}

    def api(self, method: str, path: str, payload: dict | None = None) -> dict:
        if method not in {"GET", "POST", "PUT", "PATCH"}:
            raise CapabilityBlocked("API_METHOD_FORBIDDEN")
        if not path.startswith("/") or path.startswith("//"):
            raise CapabilityBlocked("API_PATH_INVALID")
        repo_root = "/repos/" + self.repo
        if not (
            (method == "GET" and path.startswith("/installation/repositories?"))
            or (method == "POST" and path == "/graphql")
            or path == repo_root
            or path.startswith(repo_root + "/")
        ):
            raise CapabilityBlocked("API_PATH_OUTSIDE_SANDBOX")
        # No write path, including GraphQL, is available until the
        # installation token proves EXCLUSIVE access to this one sandbox.
        if method != "GET" and not self._scope_verified:
            raise CapabilityBlocked("BLOCK_PERMISSION:INSTALLATION_SCOPE_UNVERIFIED")
        # Only the two Phase-1 write classes are available. Even callers
        # invoking api() directly cannot bypass unqualified public methods.
        if method != "GET" and (method != "POST" or
                                path not in ("/graphql", repo_root + "/pulls")):
            raise CapabilityBlocked("REST_WRITE_NOT_QUALIFIED")
        if method == "POST" and path == repo_root + "/pulls":
            head = payload.get("head") if isinstance(payload, dict) else None
            if (not isinstance(head, str) or
                    not re.fullmatch(
                        r"l5-probe/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                        r"[0-9a-f]{4}-[0-9a-f]{12}", head
                    ) or
                    payload.get("draft") is not True or
                    payload.get("base") != self._default_branch or
                    head not in self._pr_push_authorizations):
                raise CapabilityBlocked("PROBE_PR_POST_NOT_QUALIFIED")
            expected_sha = self._pr_push_authorizations.get(head)
            if not isinstance(expected_sha, str) or not SHA40.fullmatch(expected_sha):
                raise CapabilityBlocked("PROBE_PR_POST_NOT_QUALIFIED")
            remote = self.branch(head)
            if ((remote.get("commit") or {}).get("sha")) != expected_sha:
                raise CapabilityBlocked("PROBE_PR_HEAD_CHANGED")
            # Consume at the underlying HTTP boundary: direct api() callers
            # cannot reuse an authorization after a lost POST response.
            self._pr_push_authorizations.pop(head, None)
        if path == "/graphql":
            query = payload.get("query") if isinstance(payload, dict) else None
            variables = payload.get("variables") if isinstance(payload, dict) else None
            node_id = variables.get("id") if isinstance(variables, dict) else None
            if not isinstance(node_id, str) or set(variables) != {"id"}:
                raise CapabilityBlocked("GRAPHQL_VARIABLES_INVALID")
            if query not in GRAPH_QUERIES:
                raise CapabilityBlocked("GRAPHQL_OPERATION_FORBIDDEN")
        # All request paths are constructed by this class; no arbitrary
        # caller-supplied REST URL can redirect a token to another host.
        request = Request(
            "https://api.github.com" + path,
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self._token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "onecompany-l5-v2-sandbox-qualifier",
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                if response.status not in {200, 201, 202, 204}:
                    raise CapabilityBlocked("REMOTE_WRITE_NOT_VERIFIED")
                try:
                    raw = response.read()
                    result = json.loads(raw) if raw else {}
                except (json.JSONDecodeError, UnicodeDecodeError, OSError, HTTPException):
                    # An applied write can return a truncated/malformed reply.
                    # Require probe readback on retry; never credit this result.
                    raise CapabilityBlocked("WAIT_EXTERNAL:MALFORMED_GITHUB_RESPONSE") from None
                if isinstance(result, dict):
                    return result
                if isinstance(result, list):
                    return {"items": result}
                raise CapabilityBlocked("WAIT_EXTERNAL:UNEXPECTED_GITHUB_RESPONSE")
        except HTTPError as exc:
            # GitHub returns 403 OR 429 on primary/secondary throttles.
            # A secondary-limit 403 may lack Retry-After and remaining=0.
            headers = exc.headers or {}
            body = b""
            if exc.code == 403:
                try:
                    body = exc.read(2048)
                except HTTPException:
                    # A truncated 403 can be a secondary-rate-limit response.
                    # Without its complete body we cannot distinguish auth
                    # rejection from transient throttling; fail retryably.
                    raise CapabilityBlocked("WAIT_EXTERNAL:TRUNCATED_GITHUB_ERROR_RESPONSE") from None
                except (OSError, TypeError, AttributeError):
                    body = b""
            reason = body.decode("utf-8", errors="replace").lower()
            secondary = any(marker in reason for marker in (
                "secondary rate limit", "rate limit exceeded",
                "api rate limit exceeded", "abuse detection mechanism",
                "please wait a few minutes before you try again",
            ))
            is_limit = exc.code == 429 or (exc.code == 403 and (
                headers.get("Retry-After") is not None or
                headers.get("x-ratelimit-remaining") == "0" or secondary
            ))
            if is_limit:
                raise CapabilityBlocked("WAIT_RATE_LIMIT") from None
            if exc.code in {401, 403}:
                raise CapabilityBlocked("BLOCK_PERMISSION:APP_REQUEST_REFUSED") from None
            # Provider-side failures can happen AFTER a successful write.
            # Classify them as transient; retry callers must reconcile the
            # stable probe ID against remote state rather than duplicate writes.
            if 500 <= exc.code <= 599:
                raise CapabilityBlocked("WAIT_EXTERNAL:GITHUB_SERVER_ERROR") from None
            raise CapabilityBlocked("REMOTE_REQUEST_FAILED:" + str(exc.code)) from None
        except (URLError, TimeoutError):
            raise CapabilityBlocked("WAIT_EXTERNAL:NETWORK_UNAVAILABLE") from None

    def _repo_api(self, method: str, suffix: str, payload: dict | None = None) -> dict:
        if (suffix and not suffix.startswith("/")) or "//" in suffix or ".." in suffix:
            raise CapabilityBlocked("API_PATH_INVALID")
        return self.api(method, "/repos/" + self.repo + suffix, payload)

    def verify_installation(self) -> dict:
        """Require an actual App token with exactly one installed sandbox.

        A token that can also write to OneCompany/Tabibi/Veritas must fail
        before invoking ANY write method or GraphQL mutation.
        """
        result = self.api("GET", "/installation/repositories?per_page=100&page=1")
        repos = result.get("repositories")
        if (
            not isinstance(repos, list)
            or result.get("total_count") != 1
            or len(repos) != 1
            or not isinstance(repos[0], dict)
        ):
            raise CapabilityBlocked("BLOCK_PERMISSION:INSTALLATION_NOT_EXCLUSIVE")
        if (repos[0].get("full_name") or "").lower() != self.repo.lower():
            raise CapabilityBlocked("BLOCK_PERMISSION:SANDBOX_OUTSIDE_INSTALLATION")
        meta = self._repo_api("GET", "")
        if meta.get("full_name", "").lower() != self.repo.lower():
            raise CapabilityBlocked("BLOCK_PERMISSION:SANDBOX_READBACK_MISMATCH")
        if meta.get("private") is not True:
            raise CapabilityBlocked("BLOCK_PERMISSION:SANDBOX_MUST_BE_PRIVATE")
        # The trusted GitHub Actions token-minting step attests the App slug.
        # Installation tokens are opaque: do not parse their internal JWT
        # or rely on the newer ghs_APPID_JWT format being universal.
        app_id = os.environ.get("L5_EXPECTED_APP_ID", "").strip()
        slug = os.environ.get("L5_ATTESTED_APP_SLUG", "").strip().lower()
        # Phase-1 sandbox is pinned to the registered App 5245673. Since
        # GitHub's Oct 2026 rollout, freshly issued installation tokens have
        # the ghs_APPID_JWT form. Match only the authenticated token's public
        # application-ID prefix; never parse or attempt to validate its JWT.
        # An opaque/legacy or different-App token is unqualified (fail closed).
        if not app_id:
            raise CapabilityBlocked("BLOCK_PERMISSION:EXPECTED_APP_ID_MISSING")
        if app_id != "5245673":
            raise CapabilityBlocked("BLOCK_PERMISSION:EXPECTED_APP_ID_MISMATCH")
        if slug != "ntinkicht-l5-sandbox":
            raise CapabilityBlocked("BLOCK_PERMISSION:APP_SLUG_ATTESTATION_FAILED")
        if not self._token.startswith("ghs_5245673_"):
            raise CapabilityBlocked("BLOCK_PERMISSION:APP_ID_NOT_ATTESTED")
        default_branch = meta.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch:
            raise CapabilityBlocked("DEFAULT_BRANCH_UNKNOWN")
        self._default_branch = default_branch
        self._scope_verified = True
        return meta

    def branch(self, branch: str) -> dict:
        if not branch.startswith("l5-probe/") or not re.fullmatch(r"l5-probe/[a-f0-9-]{36}", branch):
            raise CapabilityBlocked("PROBE_BRANCH_INVALID")
        return self._repo_api("GET", "/branches/" + branch.replace("/", "%2F"))

    def create_draft_pr(self, branch: str, base: str) -> dict:
        expected = self._pr_push_authorizations.get(branch)
        if not isinstance(expected, str) or not SHA40.fullmatch(expected):
            raise CapabilityBlocked("PROBE_PR_REQUIRES_VERIFIED_PUSH")
        if base != self._default_branch:
            raise CapabilityBlocked("PROBE_PR_BASE_MISMATCH")
        remote = self.branch(branch)
        if ((remote.get("commit") or {}).get("sha")) != expected:
            raise CapabilityBlocked("PROBE_PR_HEAD_CHANGED")
        try:
            return self._repo_api("POST", "/pulls", {
                "title": "L5 V2 sandbox App write qualification",
                "head": branch, "base": base, "draft": True,
                "body": "Sandbox-only qualification. Never use this as production review evidence.",
            })
        finally:
            # On ambiguous POST failure do not authorize any second write:
            # retrying the same probe safely stops for immutable reconciliation.
            self._pr_push_authorizations.pop(branch, None)

    def comment(self, number: int, body: str, operation_id: str) -> dict:
        """Blocked until a durable CAS lock serializes identical operations.

        A read-before-write marker alone cannot prevent simultaneous workers
        from posting duplicates. Comment capability remains UNVERIFIED.
        """
        try:
            uuid.UUID(operation_id)
        except (ValueError, TypeError, AttributeError):
            raise CapabilityBlocked("COMMENT_OPERATION_ID_INVALID") from None
        raise CapabilityBlocked("COMMENT_REQUIRES_DURABLE_CAS_LEASE")

    def request_review(self, number: int, reviewer: str) -> dict:
        """Requires a replay-safe operation record and tested reviewer gate."""
        raise CapabilityBlocked("REQUEST_REVIEW_NOT_QUALIFIED")

    def _graph_node(self, node_id: str, fragment: str) -> dict:
        if not isinstance(node_id, str) or len(node_id) > 256 or not node_id:
            raise CapabilityBlocked("NODE_ID_INVALID")
        if fragment not in (GRAPH_PR_FRAGMENT, GRAPH_THREAD_FRAGMENT):
            raise CapabilityBlocked("GRAPHQL_FRAGMENT_FORBIDDEN")
        response = self.api("POST", "/graphql", {
            "query": "query($id:ID!){node(id:$id){" + fragment + "}}",
            "variables": {"id": node_id},
        })
        if response.get("errors"):
            raise CapabilityBlocked("GRAPHQL_QUERY_FAILED")
        node = (response.get("data") or {}).get("node")
        if not isinstance(node, dict):
            raise CapabilityBlocked("GRAPHQL_NODE_UNVERIFIED")
        node_repo = (node.get("repository") or {}).get("nameWithOwner")
        if not node_repo:
            node_repo = ((node.get("pullRequest") or {}).get("repository") or {}).get("nameWithOwner")
        if (node_repo or "").lower() != self.repo.lower():
            raise CapabilityBlocked("GRAPHQL_NODE_OTHER_REPOSITORY")
        pr_number = node.get("number") if fragment == GRAPH_PR_FRAGMENT else (
            (node.get("pullRequest") or {}).get("number")
        )
        if type(pr_number) is not int or pr_number < 1:
            raise CapabilityBlocked("GRAPHQL_PROBE_PR_INVALID")
        candidate = self._repo_api("GET", f"/pulls/{pr_number}")
        if not ((candidate.get("head") or {}).get("ref") or "").startswith("l5-probe/"):
            raise CapabilityBlocked("GRAPHQL_TARGET_NOT_SANDBOX_PROBE")
        # Querying a verified node never grants mutation authority.
        # Operation-specific checks must succeed before authorization.
        return node

    def _mutate_graph(self, query: str, node_id: str, key: str) -> dict:
        try:
            response = self.api("POST", "/graphql", {
                "query": query, "variables": {"id": node_id},
            })
            if response.get("errors") or not isinstance((response.get("data") or {}).get(key), dict):
                raise CapabilityBlocked("GRAPHQL_MUTATION_NOT_VERIFIED")
            return response["data"][key]
        finally:
            # An ambiguous network failure MUST NOT leave an authorization
            # usable by a later direct GraphQL mutation call.
            self._authorized_graph_nodes.pop(node_id, None)

    def mark_ready(self, pr_node_id: str) -> dict:
        """GraphQL mutation retries are not yet durably reconciled."""
        raise CapabilityBlocked("MARK_READY_NOT_QUALIFIED")

    def resolve_thread(self, thread_id: str, pr_number: int) -> dict:
        """GraphQL mutation retries are not yet durably reconciled."""
        raise CapabilityBlocked("RESOLVE_THREAD_NOT_QUALIFIED")

    def rerun_job(self, job_id: int) -> dict:
        """Not yet qualified: a job rerun needs durable run-attempt fencing."""
        if type(job_id) is not int or job_id < 1:
            raise CapabilityBlocked("JOB_ID_INVALID")
        raise CapabilityBlocked("RERUN_JOB_NOT_QUALIFIED")

    def update_branch(self, number: int, expected_sha: str) -> dict:
        """Requires an exact-base/head fenced, replay-safe update."""
        raise CapabilityBlocked("UPDATE_BRANCH_NOT_QUALIFIED")

    def merge(self, number: int, expected_sha: str) -> dict:
        """No merge until exact head/base review is durably fenced."""
        raise CapabilityBlocked("MERGE_NOT_QUALIFIED")


def shell(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None) -> str:
    try:
        run = subprocess.run(
            cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        if cmd and cmd[0] == "git":
            raise CapabilityBlocked("WAIT_EXTERNAL:GIT_TRANSPORT_TIMEOUT") from None
        raise CapabilityBlocked("LOCAL_EXECUTION_UNAVAILABLE") from None
    except OSError:
        raise CapabilityBlocked("LOCAL_EXECUTION_UNAVAILABLE") from None
    if run.returncode:
        # Match sanitized transient conditions without ever echoing git output:
        # logs can contain URLs, credential-helper output or sensitive tokens.
        error = (run.stderr or "").lower()
        transient = (
            "could not resolve host", "couldn't resolve host",
            "temporary failure in name resolution", "connection timed out",
            "operation timed out", "connection reset", "failed to connect",
            "could not connect to server", "network is unreachable",
            "remote end hung up", "tls connect error",
            "ssl connection error", "http 500", "http 502",
            "http 503", "http 504", "the requested url returned error: 5",
        )
        if cmd and cmd[0] == "git" and any(marker in error for marker in transient):
            raise CapabilityBlocked("WAIT_EXTERNAL:GIT_TRANSPORT_FAILURE")
        raise CapabilityBlocked("LOCAL_COMMAND_FAILED:" + cmd[0])
    return run.stdout.strip()



def isolated_git_env(app: SandboxApp, askpass: Path, home: Path) -> dict[str, str]:
    """Run Git without host credentials, URL rewrites, hooks or inherited config."""
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "TMPDIR",
            "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    xdg = home / "xdg"
    xdg.mkdir(mode=0o700, exist_ok=True)
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(xdg),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": "",
        "GIT_CONFIG_KEY_1": "core.hooksPath",
        "GIT_CONFIG_VALUE_1": os.devnull,
        "GIT_ALLOW_PROTOCOL": "https",
        "L5_APP_INSTALLATION_TOKEN": app._token,
        "GIT_ASKPASS": str(askpass),
        "GIT_TERMINAL_PROMPT": "0",
    })
    return env

def write_probe_canary(target: Path, probe_id: str) -> None:
    """Create a new probe marker without following repository-owned symlinks."""
    try:
        probe_id = str(uuid.UUID(probe_id))
    except (ValueError, TypeError, AttributeError):
        raise CapabilityBlocked("PROBE_ID_INVALID") from None
    if target.is_symlink() or not target.is_dir():
        raise CapabilityBlocked("PROBE_DIRECTORY_UNSAFE")
    leaf = target / (probe_id + ".txt")
    if leaf.is_symlink() or leaf.exists():
        raise CapabilityBlocked("PROBE_FILE_ALREADY_EXISTS")
    if not hasattr(os, "O_NOFOLLOW"):
        raise CapabilityBlocked("PROBE_NOFOLLOW_UNAVAILABLE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        fd = os.open(leaf, flags, 0o600)
    except OSError:
        raise CapabilityBlocked("PROBE_FILE_CREATE_REFUSED") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("Sandbox App qualification probe ID: " + probe_id + "\n")
    except OSError:
        raise CapabilityBlocked("PROBE_FILE_WRITE_REFUSED") from None


def push_canary(app: SandboxApp, probe_id: str) -> tuple[str, str]:
    """Prove real shell checkout, single atomic git commit and fenced push."""
    if shutil.which("git") is None:
        raise CapabilityBlocked("LOCAL_EXECUTION_UNAVAILABLE:GIT")
    branch = "l5-probe/" + str(uuid.UUID(probe_id))
    with tempfile.TemporaryDirectory(prefix="l5-app-sandbox-") as directory:
        home = Path(directory)
        askpass = home / "git-askpass.sh"
        askpass.write_text(
            '#!/bin/sh\ncase "$1" in *Username*) printf "%s" "x-access-token";; '
            '*) printf "%s" "$L5_APP_INSTALLATION_TOKEN";; esac\n',
            encoding="utf-8",
        )
        askpass.chmod(0o700)
        env = isolated_git_env(app, askpass, home)
        checkout = home / "checkout"
        shell(["git", "clone", "--quiet", "https://github.com/" + app.repo + ".git", str(checkout)], env=env)
        base = shell(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=checkout, env=env)
        if not base.startswith("origin/"):
            raise CapabilityBlocked("DEFAULT_BRANCH_UNKNOWN")
        shell(["git", "checkout", "-q", "-b", branch], cwd=checkout, env=env)
        target = checkout / ".l5-sandbox-probes"
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise CapabilityBlocked("PROBE_DIRECTORY_UNSAFE")
        target.mkdir(exist_ok=True)
        write_probe_canary(target, probe_id)
        shell(["git", "add", ".l5-sandbox-probes"], cwd=checkout, env=env)
        shell(["git", "-c", "user.name=L5 Sandbox App", "-c",
               "user.email=l5-sandbox-app@users.noreply.github.com",
               "commit", "-q", "-m", "Sandbox: qualify fenced git push"], cwd=checkout, env=env)
        shell(["git", "diff", "HEAD^", "HEAD", "--check"], cwd=checkout, env=env)
        sha = shell(["git", "rev-parse", "HEAD"], cwd=checkout, env=env)
        require_sha(sha)
        # Empty expected ref protects against accidentally overwriting a branch.
        shell(["git", "push", "--quiet",
               "--force-with-lease=refs/heads/" + branch + ":",
               "origin", "HEAD:refs/heads/" + branch], cwd=checkout, env=env)
    remote = app.branch(branch)
    if (remote.get("commit") or {}).get("sha") != sha:
        raise CapabilityBlocked("PUSH_READBACK_MISMATCH")
    app._pr_push_authorizations[branch] = sha
    return branch, base.removeprefix("origin/")


def run_sandbox_push_pr(repo: str, token: str, probe_id: str) -> dict:
    """Replay-safe sandbox probe with separate evidence for push and PR writes."""
    app = SandboxApp(repo, token)
    meta = app.verify_installation()
    try:
        probe_id = str(uuid.UUID(probe_id))
    except (ValueError, TypeError, AttributeError):
        raise CapabilityBlocked("PROBE_ID_INVALID") from None
    branch = "l5-probe/" + probe_id
    base = meta.get("default_branch")
    if not isinstance(base, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", base):
        raise CapabilityBlocked("DEFAULT_BRANCH_UNKNOWN")

    # Inspect all PR states BEFORE probing the ref: GitHub often auto-deletes
    # merged head refs, but their canonical PRs must remain replayable.
    # Refuse oversized result sets rather than guessing that no PR exists.
    matching = []
    for page in range(1, 11):
        result = app._repo_api("GET", f"/pulls?state=all&per_page=100&page={page}")
        rows = result.get("items")
        if not isinstance(rows, list):
            raise CapabilityBlocked("PROBE_PR_LIST_INVALID")
        for row in rows:
            if not isinstance(row, dict):
                raise CapabilityBlocked("PROBE_PR_ENTRY_INVALID")
            head = row.get("head")
            if not isinstance(head, dict):
                raise CapabilityBlocked("PROBE_PR_HEAD_INVALID")
            head_repo = head.get("repo")
            if head_repo is not None and not isinstance(head_repo, dict):
                raise CapabilityBlocked("PROBE_PR_HEAD_REPOSITORY_INVALID")
            raw_name = (head_repo or {}).get("full_name")
            if raw_name is not None and not isinstance(raw_name, str):
                raise CapabilityBlocked("PROBE_PR_HEAD_REPOSITORY_INVALID")
            full_name = raw_name if raw_name is not None else ""
            if head.get("ref") == branch and full_name.lower() in ("", repo.lower()):
                matching.append(row)
        if len(matching) > 1:
            raise CapabilityBlocked("DUPLICATE_PROBE_PRS")
        if len(rows) < 100:
            break
    else:
        raise CapabilityBlocked("PROBE_PR_PAGINATION_LIMIT")
    prior_pr = matching[0] if matching else None

    try:
        existing = app.branch(branch)
    except CapabilityBlocked as exc:
        if str(exc) != "REMOTE_REQUEST_FAILED:404":
            raise
        existing = None

    # This phase cannot prove that an existing remote ref was pushed by the
    # intended App: a collaborator may have force-pushed an identical marker.
    # No cached PR or branch is accepted as App-authored until a durable,
    # immutable commit-SHA attestation is implemented. A retry is safe and
    # idempotent (it makes zero writes), but the probe must be requalified.
    if existing is not None or prior_pr is not None:
        raise CapabilityBlocked("PROBE_RECONCILIATION_REQUIRES_IMMUTABLE_PROOF")

    # Also refuse a previously merged probe whose marker has reached main,
    # even if GitHub no longer retains its deleted head-ref metadata.
    try:
        base_marker = app._repo_api(
            "GET", "/contents/.l5-sandbox-probes/" + probe_id + ".txt?ref=" + base
        )
    except CapabilityBlocked as exc:
        if str(exc) != "REMOTE_REQUEST_FAILED:404":
            raise
    else:
        if isinstance(base_marker, dict):
            raise CapabilityBlocked("PROBE_ID_ALREADY_ON_DEFAULT")
    branch, base = push_canary(app, probe_id)
    marker_ref = branch

    marker_path = ("/contents/.l5-sandbox-probes/" + probe_id
                   + ".txt?ref=" + marker_ref.replace("/", "%2F"))
    marker_data = app._repo_api("GET", marker_path)
    try:
        marker_text = base64.b64decode(
            marker_data["content"], validate=False
        ).decode("utf-8")
    except (KeyError, ValueError, TypeError, UnicodeDecodeError):
        raise CapabilityBlocked("PROBE_CANARY_UNVERIFIED") from None
    if marker_text != "Sandbox App qualification probe ID: " + probe_id + "\n":
        raise CapabilityBlocked("PROBE_CANARY_MISMATCH")

    pushed_sha = app._pr_push_authorizations.get(branch)
    pr = app.create_draft_pr(branch, base)
    number = pr.get("number")
    if type(number) is not int or number < 1:
        raise CapabilityBlocked("PR_CREATE_NOT_VERIFIED")
    current = app._repo_api("GET", f"/pulls/{number}")
    current_head = current.get("head")
    if not isinstance(current_head, dict) or current_head.get("ref") != branch:
        raise CapabilityBlocked("PR_READBACK_MISMATCH")
    if current_head.get("sha") != pushed_sha:
        raise CapabilityBlocked("PR_COMMIT_READBACK_MISMATCH")
    head_repo_data = current_head.get("repo")
    if head_repo_data is not None and not isinstance(head_repo_data, dict):
        raise CapabilityBlocked("PR_HEAD_OTHER_REPOSITORY")
    head_repo = (head_repo_data or {}).get("full_name")
    # Validate the raw field BEFORE lowercasing; false/0/[] must not crash
    # the CLI after the sandbox branch and PR have already been written.
    if head_repo is not None and (
            not isinstance(head_repo, str) or head_repo.lower() != repo.lower()):
        raise CapabilityBlocked("PR_HEAD_OTHER_REPOSITORY")
    # An App-scoped token can be mistakenly substituted by another bot.
    # Do not credit any App write unless GitHub attributes the created
    # canonical PR to this exact intended installation.
    user_data = current.get("user")
    author = user_data.get("login") if isinstance(user_data, dict) else None
    if not isinstance(author, str) or author.lower() != "ntinkicht-l5-sandbox[bot]":
        raise CapabilityBlocked("BLOCK_PERMISSION:PR_APP_IDENTITY_MISMATCH")

    return {
        "repo": app.repo, "sandbox_pr": number, "sandbox_branch": branch,
        "verified_write_classes": ["push", "create_pr"],
        "reconciled_write_classes": [],
        "unverified_write_classes": list(WRITE_CLASSES[2:]),
        "production_enabled": False,
        "status": "SANDBOX_PARTIAL_PROOF",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox-repo", required=True)
    parser.add_argument("--probe-id", help="stable UUID for idempotent write qualification")
    parser.add_argument("--push-pr", action="store_true",
                        help="Mutate ONLY the explicit sandbox to qualify git push and PR creation")
    args = parser.parse_args()
    try:
        repo = require_sandbox(args.sandbox_repo)
        token = os.environ.get("L5_APP_INSTALLATION_TOKEN", "")
        app = SandboxApp(repo, token)
        meta = app.verify_installation()
        if args.push_pr:
            if not args.probe_id:
                raise CapabilityBlocked("PROBE_ID_REQUIRED_FOR_WRITES")
            result = run_sandbox_push_pr(repo, token, args.probe_id)
        else:
            result = {
                "repo": repo, "default_branch": meta.get("default_branch"),
                "verified_write_classes": [], "unverified_write_classes": list(WRITE_CLASSES),
                "status": "SANDBOX_READ_ONLY_PREFLIGHT", "production_enabled": False,
            }
        print(json.dumps(result, sort_keys=True))
        return 0 if args.push_pr else 2
    except CapabilityBlocked as exc:
        reason = str(exc)
        status = reason.split(":", 1)[0] if reason.startswith("WAIT_") else "BLOCK_PERMISSION"
        print(json.dumps({"status": status,
                          "reason": reason, "production_enabled": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
