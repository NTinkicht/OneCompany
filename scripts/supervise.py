#!/usr/bin/env python3
"""Read live GitHub state and decide the next supervisory action.

The scheduler is a supervisor, not an implementer. By default this command is read-only.
Use --post-team-room only after configuring a Team Room issue and reviewing write permissions.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from onecompany_lib import CONTROL, active_implementation_leases, command_exists, github_repo_from_config, load_json, run

ACTIONABLE = {
    "START_READY_WORK",
    "RECONCILE_OPEN_PRS",
    "RECONCILE_UNLEASED_PR",
    "RECONCILE_POSSIBLY_STALE_LEASE",
    "CI_REMEDIATION_NEEDED",
    "INDEPENDENT_REVIEW_NEEDED",
    "MERGE_READY",
    "RECONCILE_CLOSED_PR_AND_SELECT_NEXT",
}


def gh_json(args: list[str]):
    result = run(["gh", *args])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return json.loads(result.stdout)


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def checks_state(items: list[dict]) -> str:
    if not items:
        return "none"
    bad = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "ERROR", "STALE"}
    pending = {"QUEUED", "IN_PROGRESS", "PENDING", "EXPECTED", "REQUESTED", "WAITING"}
    states: set[str] = set()
    for item in items:
        for key in ("conclusion", "state", "status"):
            value = item.get(key)
            if value:
                states.add(str(value).upper())
    if states & bad:
        return "failure"
    if states & pending:
        return "pending"
    return "success"


def dedup_and_post(repo: str, issue: int, action: str, head: str | None, detail: str) -> None:
    marker = f"<!-- onecompany-supervision:{action}:{head or 'none'} -->"
    recent = gh_json(["api", f"repos/{repo}/issues/{issue}/comments?per_page=50"])
    if any(marker in (item.get("body") or "") for item in recent):
        print("SUPERVISION: duplicate Team Room marker suppressed")
        return
    body = (
        f"{marker}\nSUPERVISION_CHECK\n\n"
        f"action: {action}\n"
        f"head: {head or 'none'}\n"
        f"detail: {detail}\n\n"
        "This is a liveness/reconciliation signal, not an implementation lease. "
        "Reconcile live evidence before failover or mutation."
    )
    result = run(["gh", "issue", "comment", str(issue), "--repo", repo, "--body", body])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to post Team Room comment")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-observe", action="store_true", help="Run a read-only observation even when supervision.enabled=false")
    parser.add_argument("--post-team-room", action="store_true", help="Post actionable state to the configured Team Room issue")
    args = parser.parse_args()

    if not command_exists("gh"):
        print("ERROR: GitHub CLI is required for live supervision")
        return 2

    config = load_json(CONTROL / "config.json")
    supervision = load_json(CONTROL / "supervision.json")
    state = load_json(CONTROL / "state.json")
    queue = load_json(CONTROL / "queue.json")
    repo = github_repo_from_config(config)
    if not repo:
        print("ERROR: config.project.repository must be owner/name")
        return 2

    if not supervision.get("enabled") and not args.force_observe:
        print("SUPERVISION_DISABLED: use --force-observe for a read-only check")
        return 0

    try:
        prs = gh_json(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "number,title,headRefName,headRefOid,isDraft,updatedAt"])
    except Exception as exc:
        print(f"ERROR: cannot inspect GitHub: {exc}")
        return 2

    current_pr_number = state.get("current_pr")
    current_pr = None
    if current_pr_number is not None:
        try:
            current_pr = gh_json([
                "pr", "view", str(current_pr_number), "--repo", repo,
                "--json", "number,title,state,headRefName,headRefOid,isDraft,updatedAt,statusCheckRollup"
            ])
        except Exception:
            current_pr = None

    ready_count = sum(1 for wu in queue.get("work_units", []) if wu.get("status") == "READY")
    leases = active_implementation_leases(state)
    gate = state.get("current_gate") or {}
    action = "NO_ACTION"
    detail = "No actionable transition detected."
    head = None

    if current_pr_number is not None and current_pr is None:
        action = "RECONCILE_CLOSED_PR_AND_SELECT_NEXT"
        detail = "Cached current PR is no longer open/resolvable. Reconcile before selecting next work."
    elif current_pr:
        head = current_pr.get("headRefOid")
        if current_pr.get("state") != "OPEN":
            action = "RECONCILE_CLOSED_PR_AND_SELECT_NEXT"
            detail = "Current PR is no longer open."
        elif not leases:
            action = "RECONCILE_UNLEASED_PR"
            detail = "An open canonical PR exists but no active implementation lease is recorded."
        else:
            check_state = checks_state(current_pr.get("statusCheckRollup") or [])
            if check_state == "failure":
                action = "CI_REMEDIATION_NEEDED"
                detail = "At least one deterministic check is failing on the current PR head."
            elif check_state == "success" and gate.get("sha") == head and gate.get("verdict") == "PASS — MERGE_READY" and not gate.get("stale"):
                action = "MERGE_READY"
                detail = "Required checks appear green and cached exact-head gate matches the live head; merge executor must re-verify before merge."
            elif check_state == "success":
                action = "INDEPENDENT_REVIEW_NEEDED"
                detail = "Checks appear green but no current exact-head merge-ready gate matches the live head."
            else:
                updated = parse_time(current_pr.get("updatedAt"))
                threshold = int(supervision.get("continuous_operation", {}).get("stale_candidate_minutes", 30))
                if updated and dt.datetime.now(dt.timezone.utc) - updated >= dt.timedelta(minutes=threshold):
                    action = "RECONCILE_POSSIBLY_STALE_LEASE"
                    detail = f"No PR-level durable activity is visible inside the {threshold}-minute freshness window. Verify branch/CI/job movement before failover."
                else:
                    action = "ACTIVE_WORK_IN_PROGRESS"
                    detail = "Canonical work has a lease and recent/pending deterministic activity."
    elif prs:
        action = "RECONCILE_OPEN_PRS"
        detail = "Open PRs exist but none is recorded as the canonical current PR. Do not start duplicate implementation until reconciled."
    elif ready_count > 0:
        action = "START_READY_WORK"
        detail = f"{ready_count} dependency-ready Work Unit(s) exist and no canonical PR is active. Route exactly one eligible implementer."
    else:
        action = "IDLE_NO_READY_WORK"
        detail = "No canonical PR and no READY Work Unit are visible; idle is legitimate."

    payload = {
        "action": action,
        "detail": detail,
        "repository": repo,
        "current_pr": current_pr_number,
        "head": head,
        "ready_work_count": ready_count,
        "active_implementation_leases": len(leases),
        "supervision_mode": supervision.get("mode"),
    }
    print(json.dumps(payload, indent=2))

    if args.post_team_room and action in ACTIONABLE:
        issue = supervision.get("coordination", {}).get("team_room_issue_number")
        if not isinstance(issue, int) or issue <= 0:
            print("ERROR: --post-team-room requires supervision.coordination.team_room_issue_number")
            return 2
        try:
            dedup_and_post(repo, issue, action, head, detail)
        except Exception as exc:
            print(f"ERROR: cannot post supervision marker: {exc}")
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
