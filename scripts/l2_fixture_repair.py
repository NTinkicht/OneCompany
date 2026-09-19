#!/usr/bin/env python3
"""Default-off, deterministic CI-repair worker for a PUBLIC disposable A4 PR.

This worker never creates a second PR, merges, edits arbitrary application
source, activates a provider, or grants its own authority. The installed
workflow runs reviewed default-branch code, not code from the PR.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.parse

from a4_pr_producer import (
    GitHub, Refused, SHA, _api_branch, _matching_pulls, _verify_claim,
    branch_for, fixture_body, preflight,
)
from onecompany_lib import CONTROL, load_json

CI_PATH = ".github/workflows/onecompany-l2-fixture-validation.yml"
CI_BLOB = "6b1099fe03f4adb74054d05034dc2c2c2d6e6be7"
REPAIR_LINE = "Repair: complete\n"
EVIDENCE_PREFIX = "L2_REPAIR_EVIDENCE:"


def _object(value, reason: str) -> dict:
    if not isinstance(value, dict):
        raise Refused(reason)
    return value


def _head(api: GitHub, number: int, repo: str, branch: str,
          base: str, default: str) -> str:
    doc = _object(api.call("GET", f"/pulls/{number}"), "pilot_pr_unavailable")
    head = _object(doc.get("head"), "pilot_pr_identity_invalid")
    target = _object(doc.get("base"), "pilot_pr_identity_invalid")
    head_repo = _object(head.get("repo"), "pilot_pr_identity_invalid")
    target_repo = _object(target.get("repo"), "pilot_pr_identity_invalid")
    if (doc.get("number") != number or doc.get("state") != "open"
            or doc.get("draft") is True
            or head_repo.get("full_name") != repo
            or target_repo.get("full_name") != repo
            or head.get("ref") != branch
            or target.get("ref") != default
            or target.get("sha") != base):
        raise Refused("pilot_pr_identity_drift")
    result = head.get("sha")
    if not isinstance(result, str) or not SHA.fullmatch(result):
        raise Refused("pilot_pr_head_invalid")
    return result


def _check_repaired(api: GitHub, base: str, initial: str,
                    current: str, target: str, expected: str) -> None:
    commit = _object(api.call("GET", "/git/commits/" + current),
                     "repair_commit_invalid")
    parents = commit.get("parents")
    if (not isinstance(parents, list) or len(parents) != 1
            or not isinstance(parents[0], dict)
            or parents[0].get("sha") != initial):
        raise Refused("repair_commit_not_same_canonical_pr")
    comparison = _object(api.call("GET", f"/compare/{base}...{current}"),
                         "repair_diff_invalid")
    files = comparison.get("files")
    if (not isinstance(files, list) or len(files) != 1
            or not isinstance(files[0], dict)
            or files[0].get("filename") != target
            or files[0].get("status") != "added"):
        raise Refused("repair_diff_outside_fixture_scope")
    record = _object(
        api.call("GET", "/contents/" + urllib.parse.quote(target, safe="/")
                 + "?ref=" + current),
        "repair_fixture_invalid",
    )
    encoded = record.get("content")
    if (record.get("type") != "file" or record.get("encoding") != "base64"
            or not isinstance(encoded, str)):
        raise Refused("repair_fixture_invalid")
    try:
        body = base64.b64decode(encoded, validate=False).decode("utf-8")
    except (ValueError, UnicodeError):
        raise Refused("repair_fixture_invalid") from None
    if body != expected:
        raise Refused("repair_fixture_mismatch")


def repair(api: GitHub, *, config: dict, queue: dict, readiness: dict,
           dispatch: dict, budget: dict, actors: dict, repo: str,
           actor: str, wu: str, checkout_sha: str, number: int,
           initial: str, failed_run_id: int, actions: bool,
           enabled: bool) -> dict:
    """Reconcile then append one exact repair line via non-force Git ref CAS."""
    if (api.repository != repo or not isinstance(number, int)
            or isinstance(number, bool) or number <= 0
            or not isinstance(failed_run_id, int)
            or isinstance(failed_run_id, bool) or failed_run_id <= 0
            or not isinstance(initial, str) or not SHA.fullmatch(initial)):
        raise Refused("repair_request_invalid")
    branch, target = preflight(
        config, queue, readiness, dispatch, budget, actors,
        repo=repo, actor=actor, wu=wu, base=checkout_sha,
        actions=actions, enabled=enabled,
    )
    ready = [a for a in readiness.get("actors", [])
             if isinstance(a, dict) and a.get("actor_id") == actor]
    roster = [a for a in actors.get("actors", [])
              if isinstance(a, dict) and a.get("id") == actor]
    if (len(ready) != 1 or len(roster) != 1
            or "ci_remediation" not in ready[0].get("verified_capabilities", [])
            or "ci_remediation" not in roster[0].get("capabilities", [])
            or "ci_remediation" in ready[0].get(
                "temporarily_unavailable_capabilities", [])):
        raise Refused("remediation_capability_not_verified")
    route = next((item for item in dispatch.get("actors", [])
                  if isinstance(item, dict) and item.get("actor_id") == actor), None)
    mechanisms = route.get("mechanisms") if isinstance(route, dict) else None
    if (not isinstance(mechanisms, list) or not any(
            isinstance(m, dict) and m.get("id") == "github-actions-l2-fixture-repair"
            and m.get("kind") == "github_action" and m.get("configured") is True
            and m.get("unattended") is True
            and "ci_remediation" in m.get("capabilities")
            for m in mechanisms)):
        raise Refused("l2_remediation_route_unverified")
    meta = _object(api.call("GET", "/"), "repository_identity_unknown")
    default = meta.get("default_branch")
    if (meta.get("private") is not False or meta.get("visibility") != "public"
            or default != config.get("project", {}).get("default_branch")):
        raise Refused("public_disposable_project_required")
    base = _api_branch(api, default)
    if base != checkout_sha:
        raise Refused("trusted_default_branch_changed")
    ci = _object(api.call(
        "GET", "/contents/" + CI_PATH + "?ref=" + base,
    ), "reviewed_l2_validation_workflow_missing")
    if ci.get("type") != "file" or ci.get("sha") != CI_BLOB:
        raise Refused("reviewed_l2_validation_workflow_drift")
    found = _matching_pulls(api, branch)
    if (len(found) != 1 or found[0].get("number") != number):
        raise Refused("canonical_pr_inventory_ambiguous")
    _verify_claim(api, initial, base, target, fixture_body(repo, wu, actor, base))
    body = fixture_body(repo, wu, actor, base) + REPAIR_LINE
    current = _head(api, number, repo, branch, base, default)
    if _api_branch(api, branch) != current:
        raise Refused("canonical_branch_pr_head_drift")
    if current != initial:
        _check_repaired(api, base, initial, current, target, body)
        return {
            "status": "L2_REPAIR_RECONCILED", "repository": repo,
            "work_unit": wu, "pr": number, "initial": initial,
            "repaired": current, "base": base, "already_applied": True,
        }
    run = _object(api.call("GET", f"/actions/runs/{failed_run_id}"),
                  "failed_ci_run_unavailable")
    run_repo = _object(run.get("repository"), "failed_ci_run_unavailable")
    if (run.get("event") != "workflow_dispatch"
            or run.get("path") != CI_PATH
            or run.get("head_sha") != initial
            or run.get("conclusion") != "failure"
            or run_repo.get("full_name") != repo):
        raise Refused("failed_ci_not_exact_initial_head")
    # Nothing from the failing PR is executed as producer authority.
    # Last live recheck precedes any Git object writes.
    if _head(api, number, repo, branch, base, default) != initial:
        raise Refused("pilot_head_changed_before_repair")
    parent = _object(api.call("GET", "/git/commits/" + initial),
                     "repair_parent_invalid")
    parent_tree = _object(parent.get("tree"), "repair_parent_tree_invalid")
    tree_sha = parent_tree.get("sha")
    if not isinstance(tree_sha, str) or not SHA.fullmatch(tree_sha):
        raise Refused("repair_parent_tree_invalid")
    blob = _object(api.call("POST", "/git/blobs",
                            {"content": body, "encoding": "utf-8"}),
                   "repair_blob_uncertain_reconcile")
    blob_sha = blob.get("sha")
    if not isinstance(blob_sha, str) or not SHA.fullmatch(blob_sha):
        raise Refused("repair_blob_uncertain_reconcile")
    tree = _object(api.call("POST", "/git/trees", {
        "base_tree": tree_sha,
        "tree": [{"path": target, "mode": "100644",
                  "type": "blob", "sha": blob_sha}],
    }), "repair_tree_uncertain_reconcile")
    updated_tree = tree.get("sha")
    if not isinstance(updated_tree, str) or not SHA.fullmatch(updated_tree):
        raise Refused("repair_tree_uncertain_reconcile")
    commit = _object(api.call("POST", "/git/commits", {
        "message": "test-only: repair fixture CI on existing " + branch,
        "tree": updated_tree, "parents": [initial],
    }), "repair_commit_uncertain_reconcile")
    proposed = commit.get("sha")
    if not isinstance(proposed, str) or not SHA.fullmatch(proposed):
        raise Refused("repair_commit_uncertain_reconcile")
    # Reconcile the live trust root and exact PR/ref a second time immediately
    # before the ONE ref mutation; never publish objects after base/head drift.
    if (_api_branch(api, default) != base
            or _api_branch(api, branch) != initial
            or _head(api, number, repo, branch, base, default) != initial):
        raise Refused("pilot_head_or_base_changed_before_ref")
    # An uncertain PATCH is not retried. The NEXT run reconciles exact content.
    try:
        api.call("PATCH", "/git/refs/heads/" + branch,
                 {"sha": proposed, "force": False})
    except Refused:
        raise Refused("repair_ref_indeterminate_reconcile_no_retry") from None
    if (_api_branch(api, branch) != proposed
            or _head(api, number, repo, branch, base, default) != proposed):
        raise Refused("repair_ref_indeterminate_reconcile_no_retry")
    _check_repaired(api, base, initial, proposed, target, body)
    return {
        "status": "L2_REPAIR_COMMITTED", "repository": repo,
        "work_unit": wu, "pr": number, "initial": initial,
        "repaired": proposed, "base": base, "already_applied": False,
        "failed_ci_run_id": failed_run_id,
    }


def main() -> int:
    try:
        repo, token = os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GH_TOKEN", "")
        args = (os.getenv("L2_PR_NUMBER", ""), os.getenv("L2_FAILED_RUN_ID", ""))
        if not all(value.isdecimal() and int(value) > 0 for value in args):
            raise Refused("pilot_pr_and_failed_run_required")
        checkout = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        result = repair(
            GitHub(repo, token),
            config=load_json(CONTROL / "config.json"),
            queue=load_json(CONTROL / "queue.json"),
            readiness=load_json(CONTROL / "readiness.json"),
            dispatch=load_json(CONTROL / "dispatch.json"),
            budget=load_json(CONTROL / "budget.json"),
            actors=load_json(CONTROL / "actors.json"),
            repo=repo, actor=os.getenv("A4_ACTOR", ""),
            wu=os.getenv("A4_WORK_UNIT", ""),
            checkout_sha=checkout, number=int(args[0]),
            initial=os.getenv("L2_INITIAL_HEAD", ""),
            failed_run_id=int(args[1]),
            actions=os.getenv("GITHUB_ACTIONS") == "true",
            enabled=os.getenv("ONECOMPANY_L2_FIXTURE_REPAIR_ENABLED") == "true",
        )
    except (Refused, OSError, subprocess.CalledProcessError) as exc:
        reason = str(exc) if isinstance(exc, Refused) else "runtime_unavailable"
        print("L2_REPAIR_REFUSED:" + reason, file=sys.stderr)
        return 2
    print(EVIDENCE_PREFIX + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
