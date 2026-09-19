"""Private, default-disabled exact-ref GitHub App writer.

There is intentionally NO model-visible MCP write tool yet. Before exposure,
native OneCompany durable lease validation, OAuth write-scope isolation,
independent security review and a real bot-authored smoke are required.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import urllib.parse

from github_app import AdapterRefused, AppClient
from write_authority import VerifiedWriterReadSide
from write_policy import WriteRequest, WriteRefused

_SHA = re.compile(r"^[0-9a-f]{40}$")


class ExactRefWriter:
    def __init__(self, client: AppClient):
        self.client = client
        self.authority = VerifiedWriterReadSide(client)

    @staticmethod
    def feature_enabled() -> bool:
        return os.environ.get("ONECOMPANY_GROK_WRITE_ENABLED") == "true"

    def _write_token(self) -> str:
        """Mint OneCompany-only token; never expose it in a tool response."""
        app_jwt = self.client._jwt()
        app = self.client._stage_call(
            "writer_app", "GET", "/app", app_jwt,
        )
        if (not isinstance(app, dict)
                or app.get("id") != self.client.settings.app_id
                or app.get("slug") != "onecompany-grok-worker"):
            raise WriteRefused("writer_app_identity_unverified")
        repo = self.client.settings.repository
        if repo != "NTinkicht/OneCompany":
            raise WriteRefused("writer_repository_not_approved")
        assignment = self.client._stage_call(
            "writer_installation", "GET", f"/repos/{repo}/installation",
            app_jwt,
        )
        iid = assignment.get("id") if isinstance(assignment, dict) else None
        if not isinstance(iid, int) or iid <= 0:
            raise WriteRefused("writer_installation_unverified")
        permissions = {
            "contents": "write",
            "pull_requests": "read",
            "issues": "read",
        }
        reply = self.client._stage_call(
            "writer_token", "POST",
            f"/app/installations/{iid}/access_tokens", app_jwt,
            {"repositories": [repo.split("/", 1)[1]],
             "permissions": permissions},
        )
        if not isinstance(reply, dict):
            raise WriteRefused("writer_token_invalid")
        granted = reply.get("permissions")
        repos = reply.get("repositories")
        if (not isinstance(reply.get("token"), str)
                or len(reply["token"]) < 20
                or granted is None
                or not isinstance(granted, dict)
                or any(granted.get(k) != v for k, v in permissions.items())
                or reply.get("repository_selection") != "selected"
                or not isinstance(repos, list) or len(repos) != 1
                or not isinstance(repos[0], dict)
                or repos[0].get("full_name") != repo):
            raise WriteRefused("writer_token_scope_unverified")
        return reply["token"]

    def _read_current_pr(self, pr_number: int, token: str) -> dict:
        doc = self.client._stage_call(
            "writer_pr_recheck", "GET",
            f"/repos/{self.client.settings.repository}/pulls/{pr_number}",
            token,
        )
        if not isinstance(doc, dict):
            raise WriteRefused("writer_live_pr_unavailable")
        return doc

    def _cas_file(self, request: WriteRequest, branch: str, token: str,
                  expected_blob_sha: str | None) -> str:
        """SINGLE branch update, fast-forward only. No force, merge or PR update."""
        repo = self.client.settings.repository
        target_path = urllib.parse.quote(request.path, safe="/")
        current_pr = self._read_current_pr(request.pr_number, token)
        head = current_pr.get("head")
        if not isinstance(head, dict) or not isinstance(head.get("repo"), dict):
            raise WriteRefused("writer_canonical_branch_changed")
        if head.get("sha") != request.expected_head_sha:
            raise WriteRefused("writer_head_changed_before_git_objects")
        if (head.get("ref") != branch
                or head["repo"].get("full_name") != repo):
            raise WriteRefused("writer_canonical_branch_changed")
        try:
            current = self.client._stage_call(
                "writer_file", "GET",
                f"/repos/{repo}/contents/{target_path}?ref={request.expected_head_sha}",
                token,
            )
        except AdapterRefused as exc:
            if str(exc) != "github_writer_file_github_http_status_404":
                raise
            current = None
        if current is None:
            if expected_blob_sha is not None:
                raise WriteRefused("writer_file_went_missing")
        elif (not isinstance(current, dict) or current.get("type") != "file"
              or not isinstance(current.get("sha"), str)
              or expected_blob_sha != current["sha"]):
            raise WriteRefused("writer_file_blob_cas_mismatch")
        parent = self.client._stage_call(
            "writer_commit_parent", "GET",
            f"/repos/{repo}/git/commits/{request.expected_head_sha}",
            token,
        )
        parent_tree = (parent.get("tree") or {}).get("sha") if isinstance(parent, dict) else None
        if not isinstance(parent_tree, str) or not _SHA.fullmatch(parent_tree):
            raise WriteRefused("writer_parent_tree_unverified")
        blob = self.client._stage_call(
            "writer_blob", "POST", f"/repos/{repo}/git/blobs", token,
            {"content": request.content, "encoding": "utf-8"},
        )
        blob_sha = blob.get("sha") if isinstance(blob, dict) else None
        if not isinstance(blob_sha, str) or not _SHA.fullmatch(blob_sha):
            raise WriteRefused("writer_blob_invalid")
        tree = self.client._stage_call(
            "writer_tree", "POST", f"/repos/{repo}/git/trees", token,
            {"base_tree": parent_tree,
             "tree": [{"path": request.path, "mode": "100644",
                       "type": "blob", "sha": blob_sha}]},
        )
        tree_sha = tree.get("sha") if isinstance(tree, dict) else None
        if not isinstance(tree_sha, str) or not _SHA.fullmatch(tree_sha):
            raise WriteRefused("writer_tree_invalid")
        commit = self.client._stage_call(
            "writer_commit", "POST", f"/repos/{repo}/git/commits", token,
            {"message": f"feat({request.work_unit}): scoped bot contribution",
             "tree": tree_sha, "parents": [request.expected_head_sha]},
        )
        commit_sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(commit_sha, str) or not _SHA.fullmatch(commit_sha):
            raise WriteRefused("writer_commit_invalid")
        return commit_sha

    def submit(self, request: WriteRequest,
               expected_blob_sha: str | None) -> dict:
        if not self.feature_enabled():
            raise WriteRefused("writer_disabled")
        if expected_blob_sha is not None and (
            not isinstance(expected_blob_sha, str)
            or not _SHA.fullmatch(expected_blob_sha)
        ):
            raise WriteRefused("expected_blob_sha_invalid")
        if self.client.settings.repository != "NTinkicht/OneCompany":
            raise WriteRefused("writer_repository_not_approved")
        # Read-side witness is materialized by the server, not Grok.
        before = self.authority.inspect(
            request, now=dt.datetime.now(dt.timezone.utc),
            feature_enabled=True,
        )
        token = self._write_token()
        branch = before["branch"]
        candidate = self._cas_file(
            request, branch, token, expected_blob_sha,
        )
        # Never trust a stale snapshot after constructing Git objects.
        latest = self.authority.inspect(
            request, now=dt.datetime.now(dt.timezone.utc),
            feature_enabled=True,
        )
        if latest["branch"] != branch or latest["expected_head_sha"] != request.expected_head_sha:
            raise WriteRefused("writer_lease_or_head_changed_before_ref")
        repo = self.client.settings.repository
        current = self._read_current_pr(request.pr_number, token)
        current_head, current_base = current.get("head"), current.get("base")
        if (not isinstance(current_head, dict)
                or not isinstance(current_base, dict)
                or current_head.get("sha") != request.expected_head_sha
                or current_head.get("ref") != branch
                or current_base.get("sha") != latest["main_sha"]):
            raise WriteRefused("writer_pr_changed_before_ref")
        # PATCH is the only mutation to a Git ref. A sibling commit based on
        # a stale head fails GitHub's fast-forward-only reference update.
        result = self.client._stage_call(
            "writer_ref_cas", "PATCH",
            f"/repos/{repo}/git/refs/heads/{urllib.parse.quote(branch, safe='')}",
            token, {"sha": candidate, "force": False},
        )
        updated_sha = ((result.get("object") or {}).get("sha")
                       if isinstance(result, dict) else None)
        if updated_sha != candidate:
            raise WriteRefused("writer_ref_indeterminate_reconcile_no_retry")
        pr = self._read_current_pr(request.pr_number, token)
        # The ref may already have moved. Malformed identity here is an
        # indeterminate write outcome, never a safe-to-retry exception.
        pr_head, pr_base = pr.get("head"), pr.get("base")
        if (not isinstance(pr_head, dict) or not isinstance(pr_base, dict)
                or pr_head.get("sha") != candidate
                or pr_head.get("ref") != branch
                or pr_base.get("sha") != latest["main_sha"]):
            raise WriteRefused("writer_pr_indeterminate_reconcile_no_retry")
        return {
            "work_unit": request.work_unit, "lease_id": request.lease_id,
            "pr_number": request.pr_number, "branch": branch,
            "previous_head": request.expected_head_sha, "new_head": candidate,
            "authenticated_principal": "onecompany-grok-worker[bot]",
            "merge_executed": False, "review_attestation": False,
            "unattended": False,
        }
