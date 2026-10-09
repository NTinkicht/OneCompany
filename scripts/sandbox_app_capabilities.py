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
        self._authorized_graph_nodes: dict[str, str] = {}

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
        if path == "/graphql":
            query = payload.get("query") if isinstance(payload, dict) else None
            variables = payload.get("variables") if isinstance(payload, dict) else None
            node_id = variables.get("id") if isinstance(variables, dict) else None
            if not isinstance(node_id, str) or set(variables) != {"id"}:
                raise CapabilityBlocked("GRAPHQL_VARIABLES_INVALID")
            if query not in GRAPH_QUERIES and query not in (
                GRAPH_READY_MUTATION, GRAPH_RESOLVE_MUTATION
            ):
                raise CapabilityBlocked("GRAPHQL_OPERATION_FORBIDDEN")
            if query in (GRAPH_READY_MUTATION, GRAPH_RESOLVE_MUTATION):
                operation = "ready" if query == GRAPH_READY_MUTATION else "resolve"
                if self._authorized_graph_nodes.get(node_id) != operation:
                    raise CapabilityBlocked("GRAPHQL_MUTATION_TARGET_UNVERIFIED")
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
                raw = response.read()
                result = json.loads(raw) if raw else {}
                return result if isinstance(result, dict) else {"items": result}
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise CapabilityBlocked("BLOCK_PERMISSION:APP_REQUEST_REFUSED") from None
            if exc.code == 429:
                raise CapabilityBlocked("WAIT_RATE_LIMIT") from None
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
        if not isinstance(repos, list) or result.get("total_count") != 1 or len(repos) != 1:
            raise CapabilityBlocked("BLOCK_PERMISSION:INSTALLATION_NOT_EXCLUSIVE")
        if (repos[0].get("full_name") or "").lower() != self.repo.lower():
            raise CapabilityBlocked("BLOCK_PERMISSION:SANDBOX_OUTSIDE_INSTALLATION")
        meta = self._repo_api("GET", "")
        if meta.get("full_name", "").lower() != self.repo.lower():
            raise CapabilityBlocked("BLOCK_PERMISSION:SANDBOX_READBACK_MISMATCH")
        if meta.get("private") is not True:
            raise CapabilityBlocked("BLOCK_PERMISSION:SANDBOX_MUST_BE_PRIVATE")
        self._scope_verified = True
        return meta

    def branch(self, branch: str) -> dict:
        if not branch.startswith("l5-probe/") or not re.fullmatch(r"l5-probe/[a-f0-9-]{36}", branch):
            raise CapabilityBlocked("PROBE_BRANCH_INVALID")
        return self._repo_api("GET", "/branches/" + branch.replace("/", "%2F"))

    def create_draft_pr(self, branch: str, base: str) -> dict:
        return self._repo_api("POST", "/pulls", {
            "title": "L5 V2 sandbox App write qualification",
            "head": branch, "base": base, "draft": True,
            "body": "Sandbox-only qualification. Never use this as production review evidence.",
        })

    def comment(self, number: int, body: str, operation_id: str) -> dict:
        """Post at most one sandbox comment per stable operation identity."""
        try:
            marker = "<!-- l5-sandbox-comment:" + str(uuid.UUID(operation_id)) + " -->"
        except (ValueError, TypeError, AttributeError):
            raise CapabilityBlocked("COMMENT_OPERATION_ID_INVALID") from None
        pr = self._repo_api("GET", f"/pulls/{number}")
        head = ((pr.get("head") or {}).get("ref") or "")
        if not head.startswith("l5-probe/"):
            raise CapabilityBlocked("COMMENT_TARGET_NOT_PROBE")
        for page in range(1, 11):
            result = self._repo_api(
                "GET", f"/issues/{number}/comments?per_page=100&page={page}"
            )
            comments = result.get("items")
            if not isinstance(comments, list):
                raise CapabilityBlocked("COMMENTS_READBACK_INVALID")
            found = [item for item in comments
                     if marker in (item.get("body") or "")]
            if len(found) > 1:
                raise CapabilityBlocked("DUPLICATE_OPERATION_COMMENT")
            if found:
                return {"reconciled": True, "comment": found[0]}
            if len(comments) < 100:
                break
        else:
            raise CapabilityBlocked("COMMENT_PAGINATION_LIMIT")
        created = self._repo_api(
            "POST", f"/issues/{number}/comments",
            {"body": body + "\n\n" + marker},
        )
        if marker not in (created.get("body") or ""):
            raise CapabilityBlocked("COMMENT_READBACK_MISMATCH")
        return {"reconciled": False, "comment": created}

    def request_review(self, number: int, reviewer: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", reviewer):
            raise CapabilityBlocked("REVIEWER_INVALID")
        return self._repo_api(
            "POST", f"/pulls/{number}/requested_reviewers", {"reviewers": [reviewer]}
        )

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
        self._authorized_graph_nodes[node_id] = (
            "ready" if fragment == GRAPH_PR_FRAGMENT else "resolve"
        )
        return node

    def _mutate_graph(self, query: str, node_id: str, key: str) -> dict:
        response = self.api("POST", "/graphql", {
            "query": query, "variables": {"id": node_id},
        })
        if response.get("errors") or not isinstance((response.get("data") or {}).get(key), dict):
            raise CapabilityBlocked("GRAPHQL_MUTATION_NOT_VERIFIED")
        self._authorized_graph_nodes.pop(node_id, None)
        return response["data"][key]

    def mark_ready(self, pr_node_id: str) -> dict:
        node = self._graph_node(
            pr_node_id,
            GRAPH_PR_FRAGMENT,
        )
        if node.get("isDraft") is not True:
            raise CapabilityBlocked("PR_NOT_DRAFT")
        return self._mutate_graph(
            GRAPH_READY_MUTATION,
            pr_node_id, "markPullRequestReadyForReview",
        )

    def resolve_thread(self, thread_id: str, pr_number: int) -> dict:
        node = self._graph_node(
            thread_id,
            GRAPH_THREAD_FRAGMENT,
        )
        if (node.get("pullRequest") or {}).get("number") != pr_number:
            raise CapabilityBlocked("THREAD_NOT_ON_PROBE_PR")
        if node.get("isResolved") is True:
            raise CapabilityBlocked("THREAD_ALREADY_RESOLVED")
        return self._mutate_graph(
            GRAPH_RESOLVE_MUTATION,
            thread_id, "resolveReviewThread",
        )

    def rerun_job(self, job_id: int) -> dict:
        if type(job_id) is not int or job_id < 1:
            raise CapabilityBlocked("JOB_ID_INVALID")
        return self._repo_api("POST", f"/actions/jobs/{job_id}/rerun", {})

    def update_branch(self, number: int, expected_sha: str) -> dict:
        return self._repo_api(
            "PUT", f"/pulls/{number}/update-branch",
            {"expected_head_sha": require_sha(expected_sha)},
        )

    def merge(self, number: int, expected_sha: str) -> dict:
        """Sandbox-only test merge; no production endpoint is accessible."""
        current = self._repo_api("GET", f"/pulls/{number}")
        if (current.get("head") or {}).get("sha") != require_sha(expected_sha):
            raise CapabilityBlocked("MERGE_STALE_HEAD")
        return self._repo_api(
            "PUT", f"/pulls/{number}/merge",
            {"sha": expected_sha, "merge_method": "squash"},
        )


def shell(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None) -> str:
    try:
        run = subprocess.run(
            cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CapabilityBlocked("LOCAL_EXECUTION_UNAVAILABLE") from exc
    if run.returncode:
        # Never echo stderr/stdout; git might reveal checkout URL or credentials.
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
        (target / (branch.split("/", 1)[1] + ".txt")).write_text(
            "Sandbox App qualification probe ID: " + probe_id + "\n",
            encoding="utf-8",
        )
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
    return branch, base.removeprefix("origin/")


def run_sandbox_push_pr(repo: str, token: str, probe_id: str) -> dict:
    """Reconcile one stable probe across retries, never create a second WU."""
    app = SandboxApp(repo, token)
    app.verify_installation()
    try:
        probe_id = str(uuid.UUID(probe_id))
    except (ValueError, TypeError, AttributeError):
        raise CapabilityBlocked("PROBE_ID_INVALID") from None
    branch = "l5-probe/" + probe_id
    # Read back the exact probe first. A lost response MUST NOT create a
    # second branch or PR with another identity.
    try:
        existing = app.branch(branch)
    except CapabilityBlocked as exc:
        if str(exc) != "REMOTE_REQUEST_FAILED:404":
            raise
        existing = None
    reconciled = existing is not None
    if reconciled:
        if not SHA40.fullmatch((existing.get("commit") or {}).get("sha", "")):
            raise CapabilityBlocked("PROBE_BRANCH_SHA_INVALID")
        base = app.verify_installation().get("default_branch")
        if not isinstance(base, str) or not base:
            raise CapabilityBlocked("DEFAULT_BRANCH_UNKNOWN")
    else:
        branch, base = push_canary(app, probe_id)
    # Read back a probe-specific marker in the actual remote commit. Existing
    # objects are reconciled, NEVER re-credited as fresh App writes.
    marker_path = "/contents/.l5-sandbox-probes/" + probe_id + ".txt?ref=" + branch.replace("/", "%2F")
    marker_data = app._repo_api("GET", marker_path)
    try:
        marker_text = base64.b64decode(marker_data["content"], validate=False).decode("utf-8")
    except (KeyError, ValueError, TypeError, UnicodeDecodeError):
        raise CapabilityBlocked("PROBE_CANARY_UNVERIFIED") from None
    if marker_text != "Sandbox App qualification probe ID: " + probe_id + "\n":
        raise CapabilityBlocked("PROBE_CANARY_MISMATCH")
    listed = app._repo_api("GET", "/pulls?state=all&head=" + repo.split("/")[0] + ":" + branch)
    matching = [x for x in listed.get("items", [])
                if (x.get("head") or {}).get("ref") == branch]
    if len(matching) > 1:
        raise CapabilityBlocked("DUPLICATE_PROBE_PRS")
    if matching:
        pr = matching[0]
    else:
        try:
            pr = app.create_draft_pr(branch, base)
        except CapabilityBlocked:
            # Ambiguous remote response: next invocation will reconcile using
            # the SAME --probe-id; never mint another probe.
            raise
    number = pr.get("number")
    if type(number) is not int or number < 1:
        raise CapabilityBlocked("PR_CREATE_NOT_VERIFIED")
    current = app._repo_api("GET", f"/pulls/{number}")
    if (current.get("head") or {}).get("ref") != branch:
        raise CapabilityBlocked("PR_READBACK_MISMATCH")
    return {
        "repo": app.repo, "sandbox_pr": number, "sandbox_branch": branch,
        "verified_write_classes": [] if reconciled else ["push", "create_pr"],
        "reconciled_write_classes": ["push", "create_pr"] if reconciled else [],
        "unverified_write_classes": list(WRITE_CLASSES[2:]),
        "production_enabled": False,
        "status": "SANDBOX_RECONCILED_PREVIOUS_OPERATION" if reconciled else "SANDBOX_PARTIAL_PROOF",
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
        print(json.dumps({"status": "BLOCK_PERMISSION",
                          "reason": str(exc), "production_enabled": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
