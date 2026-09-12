#!/usr/bin/env python3
"""Read live GitHub + durable ledger and decide the next supervisory action."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from ledger_lib import derive, ledger_enabled, list_events
from onecompany_lib import CONTROL, active_implementation_leases, command_exists, emergency_stop_active, github_repo_from_config, load_json, run

ACTIONABLE = {"START_READY_WORK", "RECONCILE_OPEN_PRS", "RECONCILE_UNLEASED_PR", "RECONCILE_POSSIBLY_STALE_LEASE", "CI_REMEDIATION_NEEDED", "INDEPENDENT_REVIEW_NEEDED", "MERGE_READY", "RECONCILE_CLOSED_PR_AND_SELECT_NEXT"}


def gh_json(args: list[str]):
    result = run(["gh", *args])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return json.loads(result.stdout)


def parse_time(value: str | None):
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
            if item.get(key):
                states.add(str(item.get(key)).upper())
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
    body = f"{marker}\nSUPERVISION_CHECK\n\naction: {action}\nhead: {head or 'none'}\ndetail: {detail}\n\nThis is a liveness signal, not an implementation lease."
    result = run(["gh", "issue", "comment", str(issue), "--repo", repo, "--body", body])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to post Team Room comment")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-observe", action="store_true")
    parser.add_argument("--post-team-room", action="store_true")
    args = parser.parse_args()
    if not command_exists("gh"):
        print("ERROR: GitHub CLI is required")
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
    if emergency_stop_active(config):
        print(json.dumps({"action": "EMERGENCY_STOP_ACTIVE", "detail": "Autonomous mutation is frozen; read-only diagnosis and safe containment may continue.", "repository": repo}, indent=2))
        return 0

    try:
        prs = gh_json(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "number,title,headRefName,headRefOid,isDraft,updatedAt"])
    except Exception as exc:
        print(f"ERROR: cannot inspect GitHub: {exc}")
        return 2

    ledger_events: list[dict] = []
    active = active_implementation_leases(state)
    gate = state.get("current_gate")
    current_pr_number = state.get("current_pr")
    if ledger_enabled():
        try:
            ledger_events = list_events()
            global_view = derive(ledger_events)
            active = [item for item in global_view.get("active_leases", []) if item.get("role") == "implementation"]
            ledger_prs = {item.get("pr") for item in active if isinstance(item.get("pr"), int)}
            if current_pr_number is None and len(ledger_prs) == 1:
                current_pr_number = next(iter(ledger_prs))
            gate = derive(ledger_events, current_pr_number).get("current_gate") if current_pr_number else None
        except Exception as exc:
            print(f"ERROR: cannot inspect durable coordination ledger: {exc}")
            return 2

    current_pr = None
    if current_pr_number is not None:
        try:
            current_pr = gh_json(["pr", "view", str(current_pr_number), "--repo", repo, "--json", "number,title,state,headRefName,headRefOid,isDraft,updatedAt,statusCheckRollup"])
        except Exception:
            current_pr = None

    ready_count = sum(1 for wu in queue.get("work_units", []) if wu.get("status") == "READY")
    action = "NO_ACTION"; detail = "No actionable transition detected."; head = None
    if current_pr_number is not None and current_pr is None:
        action = "RECONCILE_CLOSED_PR_AND_SELECT_NEXT"; detail = "Cached/ledger PR is no longer open/resolvable."
    elif current_pr:
        head = current_pr.get("headRefOid")
        current_active = [item for item in active if item.get("pr") in {None, current_pr_number}]
        if current_pr.get("state") != "OPEN":
            action = "RECONCILE_CLOSED_PR_AND_SELECT_NEXT"; detail = "Current PR is no longer open."
        elif not current_active:
            action = "RECONCILE_UNLEASED_PR"; detail = "Open canonical PR exists but no active implementation lease is durable."
        else:
            check_state = checks_state(current_pr.get("statusCheckRollup") or [])
            if check_state == "failure":
                action = "CI_REMEDIATION_NEEDED"; detail = "At least one deterministic check is failing on current head."
            elif check_state == "success" and gate and gate.get("sha") == head and gate.get("verdict") == "PASS — MERGE_READY" and not gate.get("stale"):
                action = "MERGE_READY"; detail = "Green checks and durable trusted exact-head gate match live head; merge executor must re-verify governance and expected head."
            elif check_state == "success":
                action = "INDEPENDENT_REVIEW_NEEDED"; detail = "Checks appear green but no durable current-head merge-ready gate exists."
            else:
                updated = parse_time(current_pr.get("updatedAt"))
                threshold = int(supervision.get("continuous_operation", {}).get("stale_candidate_minutes", 30))
                if updated and dt.datetime.now(dt.timezone.utc) - updated >= dt.timedelta(minutes=threshold):
                    action = "RECONCILE_POSSIBLY_STALE_LEASE"; detail = f"No PR-level durable activity visible in {threshold} minutes; inspect live job/branch movement before failover."
                else:
                    action = "ACTIVE_WORK_IN_PROGRESS"; detail = "Canonical work has a durable lease and recent/pending deterministic activity."
    elif prs:
        action = "RECONCILE_OPEN_PRS"; detail = "Open PRs exist but no unique canonical stream is established from durable state."
    elif ready_count > 0:
        action = "START_READY_WORK"; detail = f"{ready_count} dependency-ready WU(s) exist and no canonical PR is active. Route and dispatch exactly one implementer."
    else:
        action = "IDLE_NO_READY_WORK"; detail = "No canonical PR and no READY WU; idle is legitimate."

    payload = {"action": action, "detail": detail, "repository": repo, "current_pr": current_pr_number, "head": head, "ready_work_count": ready_count, "active_implementation_leases": len(active), "durable_ledger": ledger_enabled(), "supervision_mode": supervision.get("mode")}
    print(json.dumps(payload, indent=2))
    if args.post_team_room and action in ACTIONABLE:
        issue = supervision.get("coordination", {}).get("team_room_issue_number")
        if not isinstance(issue, int) or issue <= 0:
            print("ERROR: --post-team-room requires team_room_issue_number")
            return 2
        try:
            dedup_and_post(repo, issue, action, head, detail)
        except Exception as exc:
            print(f"ERROR: cannot post supervision marker: {exc}")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
