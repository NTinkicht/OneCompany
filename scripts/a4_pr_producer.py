#!/usr/bin/env python3
"""A4c: project-scoped, deterministic first-PR producer for disposable pilots.

This module is dormant in the OneCompany source installation. A target must
separately enable the disabled workflow and a verified L2 fixture-only actor.
It creates no merge/release/deployment/database authority.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fixture_actions_adapter import fixture_path
from onecompany_lib import CONTROL, load_json

SHA = re.compile(r"^[0-9a-f]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class Refused(RuntimeError):
    """No mutation is permitted or an attempted mutation is indeterminate."""


class ApiFailure(Refused):
    def __init__(self, status: int):
        super().__init__(f"github_api_status_{status}")
        self.status = status


class GitHub:
    def __init__(self, repository: str, token: str):
        if not REPO.fullmatch(repository) or not token:
            raise Refused("repository_identity_or_github_token_missing")
        self.repository = repository
        self.token = token

    def call(self, method: str, path: str, payload: dict | None = None) -> Any:
        if not path.startswith("/") or "://" in path:
            raise Refused("invalid_api_path")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.github.com/repos/" + self.repository + path,
            data=data,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as result:
                raw = result.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            # Do not print a response body; it could include private content.
            raise ApiFailure(exc.code) from None
        except (OSError, ValueError) as exc:
            raise Refused("github_result_uncertain_reconcile_before_retry") from exc


def branch_for(wu: str) -> str:
    if fixture_path(wu) is None:
        raise Refused("invalid_fixture_work_unit")
    return "onecompany-a4-" + wu.lower()


def fixture_body(repo: str, wu: str, actor: str, base: str) -> str:
    return (
        "# OneCompany A4 isolated claim and implementation fixture\n\n"
        f"Repository: {repo}\nWork Unit: {wu}\nActor: {actor}\n"
        f"Base SHA: {base}\n"
        "Scope: deterministic test-only fixture; no deployment or release.\n"
    )


def preflight(
    config: dict, queue: dict, readiness: dict, dispatch: dict,
    *, repo: str, actor: str, wu: str, base: str,
    actions: bool, enabled: bool,
) -> tuple[str, str]:
    """Require exact project-local permissions and a READY, unbound LOW-risk WU."""
    errors: list[str] = []
    target = fixture_path(wu)
    branch = branch_for(wu)
    if not actions or not enabled:
        errors.append("unattended_fixture_producer_disabled")
    if config.get("autonomy", {}).get("level") not in {"L2", "L3", "L4", "L5"}:
        errors.append("project_l2_approval_missing")
    if config.get("safety", {}).get("emergency_stop") is not False:
        errors.append("emergency_stop_or_unknown")
    project = config.get("project", {})
    if project.get("repository") != repo or project.get("default_branch") != "main":
        errors.append("project_identity_or_default_branch_mismatch")
    if not SHA.fullmatch(base):
        errors.append("trusted_base_sha_missing")
    matching = [x for x in queue.get("work_units", [])
                if isinstance(x, dict) and x.get("id") == wu]
    if len(matching) != 1:
        errors.append("wu_missing_or_duplicated")
    else:
        item = matching[0]
        if item.get("status") != "READY" or item.get("risk_class") != "LOW":
            errors.append("wu_not_ready_low_risk")
        if item.get("branch") != branch or item.get("pr") is not None:
            errors.append("wu_not_canonically_pre_pr_bound")
        if item.get("write_scope") != [target]:
            errors.append("wu_not_exact_fixture_scope")
        if item.get("dependencies"):
            errors.append("fixture_dependencies_require_durable_proof")
    for other in queue.get("work_units", []):
        if isinstance(other, dict) and other.get("id") != wu and other.get("branch") == branch:
            errors.append("branch_reserved_by_another_wu")
    people = [x for x in readiness.get("actors", []) if x.get("actor_id") == actor]
    if len(people) != 1:
        errors.append("actor_not_in_verified_registry")
    else:
        person = people[0]
        if (person.get("setup_state") != "ready"
            or "implementation" not in person.get("verified_capabilities", [])
            or person.get("repository_access", {}).get("write") is not True
            or person.get("unattended", {}).get("verified") is not True):
            errors.append("actor_unattended_write_unverified")
    routes = [x for x in dispatch.get("actors", []) if x.get("actor_id") == actor]
    mechanisms = (routes[0].get("mechanisms", []) if len(routes) == 1 else [])
    if not any(
        m.get("id") == "github-actions-a4-pr-producer"
        and m.get("kind") == "github_action"
        and m.get("configured") is True and m.get("unattended") is True
        and "implementation" in m.get("capabilities", [])
        for m in mechanisms
    ):
        errors.append("producer_dispatch_route_not_verified")
    if errors:
        raise Refused(",".join(sorted(set(errors))))
    assert target is not None
    return branch, target


def _api_branch(api: GitHub, branch: str) -> str | None:
    try:
        ref = api.call("GET", "/git/ref/heads/" + branch)
    except ApiFailure as exc:
        if exc.status == 404:
            return None
        raise
    result = ref.get("object", {}).get("sha")
    if not isinstance(result, str) or not SHA.fullmatch(result):
        raise Refused("branch_ref_ambiguous")
    return result


def _matching_pulls(api: GitHub, branch: str) -> list[dict]:
    owner = api.repository.split("/", 1)[0]
    query = urllib.parse.urlencode({
        "state": "all", "head": owner + ":" + branch,
        "base": "main", "per_page": "100",
    })
    result = api.call("GET", "/pulls?" + query)
    if not isinstance(result, list) or len(result) >= 100:
        raise Refused("pull_request_inventory_ambiguous")
    return result


def _verify_claim(api: GitHub, head: str, base: str, target: str, body: str) -> None:
    commit = api.call("GET", "/git/commits/" + head)
    parents = commit.get("parents", [])
    if len(parents) != 1 or parents[0].get("sha") != base:
        raise Refused("pre_existing_branch_not_exact_claim")
    path = urllib.parse.quote(target, safe="/")
    record = api.call("GET", "/contents/" + path + "?ref=" + head)
    if record.get("type") != "file" or record.get("encoding") != "base64":
        raise Refused("claim_fixture_missing_or_invalid")
    try:
        existing = base64.b64decode(record["content"], validate=False).decode("utf-8")
    except (KeyError, UnicodeError, ValueError) as exc:
        raise Refused("claim_fixture_unreadable") from exc
    if existing != body:
        raise Refused("pre_existing_branch_claim_conflict")


def _create_claim(api: GitHub, base: str, branch: str, target: str, body: str) -> str:
    base_commit = api.call("GET", "/git/commits/" + base)
    tree_sha = base_commit.get("tree", {}).get("sha")
    if not isinstance(tree_sha, str) or not SHA.fullmatch(tree_sha):
        raise Refused("base_tree_unavailable")
    blob = api.call("POST", "/git/blobs", {"content": body, "encoding": "utf-8"})
    tree = api.call("POST", "/git/trees", {
        "base_tree": tree_sha,
        "tree": [{"path": target, "mode": "100644", "type": "blob", "sha": blob["sha"]}],
    })
    commit = api.call("POST", "/git/commits", {
        "message": "test-only: reserve and implement " + branch,
        "tree": tree["sha"], "parents": [base],
    })
    proposed = commit.get("sha")
    if not isinstance(proposed, str) or not SHA.fullmatch(proposed):
        raise Refused("claim_commit_unavailable")
    try:
        api.call("POST", "/git/refs", {
            "ref": "refs/heads/" + branch, "sha": proposed,
        })
    except (ApiFailure, Refused):
        # Branch creation can succeed even if the response is lost. Read back
        # the single canonical ref; never blindly create a competing branch.
        current = _api_branch(api, branch)
        if current is None:
            raise Refused("claim_creation_uncertain_reconcile_before_retry")
        _verify_claim(api, current, base, target, body)
        return current
    current = _api_branch(api, branch)
    if current != proposed:
        raise Refused("canonical_claim_ref_moved")
    return proposed


def produce(api: GitHub, *, config: dict, queue: dict, readiness: dict,
            dispatch: dict, repo: str, actor: str, wu: str,
            checkout_sha: str, actions: bool, enabled: bool) -> dict:
    """Reserve one Git ref atomically, then create/adopt one canonical open PR."""
    meta = api.call("GET", "")
    default = meta.get("default_branch")
    base_data = api.call("GET", "/git/ref/heads/main")
    base = base_data.get("object", {}).get("sha")
    if default != "main" or not isinstance(base, str) or base != checkout_sha:
        raise Refused("trusted_checkout_or_base_moved")
    branch, target = preflight(
        config, queue, readiness, dispatch, repo=repo, actor=actor, wu=wu,
        base=base, actions=actions, enabled=enabled,
    )
    body = fixture_body(repo, wu, actor, base)
    # Unmanaged existing PRs/branches cannot be overwritten or reclassified.
    found = _matching_pulls(api, branch)
    if len(found) > 1:
        raise Refused("duplicate_canonical_pr_inventory")
    head = _api_branch(api, branch)
    if head is None:
        if found:
            raise Refused("pr_exists_without_canonical_branch")
        head = _create_claim(api, base, branch, target, body)
    _verify_claim(api, head, base, target, body)
    found = _matching_pulls(api, branch)
    if len(found) > 1:
        raise Refused("duplicate_canonical_pr_inventory")
    if found:
        pr = found[0]
        if pr.get("state") != "open" or pr.get("draft") is True:
            raise Refused("canonical_pr_closed_or_draft")
    else:
        if api.call("GET", "/git/ref/heads/main")["object"]["sha"] != base:
            raise Refused("base_moved_before_pr_creation")
        try:
            pr = api.call("POST", "/pulls", {
                "title": f"test-only: A4 isolated producer {wu}",
                "head": branch, "base": "main",
                "body": f"Disposable A4 pilot for {wu}; no deployment or merge authority.",
                "draft": False,
            })
        except (ApiFailure, Refused):
            # A successful API mutation can lose its response. Never retry POST
            # without inventory reconciliation and a fresh independent run.
            raise Refused("pr_creation_uncertain_reconcile_before_retry") from None
    number = pr.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise Refused("canonical_pr_number_invalid")
    live = api.call("GET", "/pulls/" + str(number))
    if (live.get("state") != "open"
        or live.get("head", {}).get("sha") != head
        or live.get("head", {}).get("ref") != branch
        or live.get("head", {}).get("repo", {}).get("full_name") != repo
        or live.get("base", {}).get("sha") != base
        or live.get("base", {}).get("repo", {}).get("full_name") != repo):
        raise Refused("created_pr_exact_identity_drift")
    return {
        "status": "PR_CREATED_OR_RECONCILED",
        "repository": repo, "work_unit": wu, "actor": actor,
        "branch": branch, "pr": number, "head": head,
        "base": base, "fixture_path": target,
        "note": "Source CI, independent review and merge remain separate gates.",
    }


def main() -> int:
    try:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GH_TOKEN", "")
        actor = os.environ.get("A4_ACTOR", "")
        wu = os.environ.get("A4_WORK_UNIT", "")
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            check=True,
        ).stdout.strip()
        answer = produce(
            GitHub(repo, token),
            config=load_json(CONTROL / "config.json"),
            queue=load_json(CONTROL / "queue.json"),
            readiness=load_json(CONTROL / "readiness.json"),
            dispatch=load_json(CONTROL / "dispatch.json"),
            repo=repo, actor=actor, wu=wu, checkout_sha=sha,
            actions=os.environ.get("GITHUB_ACTIONS") == "true",
            enabled=os.environ.get("ONECOMPANY_A4_PRODUCER_ENABLED") == "true",
        )
    except (Refused, subprocess.CalledProcessError, OSError) as exc:
        print("A4_REFUSED: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(answer, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
