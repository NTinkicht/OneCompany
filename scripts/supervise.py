#!/usr/bin/env python3
"""Read live GitHub + coordination events and decide conflict-aware supervisory actions."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from capacity_lib import implementation_pool
from lease_lifecycle import coordination_view
from ledger_lib import ledger_enabled
from onecompany_lib import (
    CONTROL,
    autonomy_number,
    command_exists,
    emergency_stop_active,
    github_repo_from_config,
    load_json,
    run,
)
from planning_lib import select_parallel_set

ACTIONABLE = {
    "START_READY_WORK",
    "START_PARALLEL_READY_WORK",
    "RECONCILE_OPEN_PRS",
    "RECONCILE_UNLEASED_PR",
    "RECONCILE_POSSIBLY_STALE_LEASE",
    "CI_REMEDIATION_NEEDED",
    "INDEPENDENT_REVIEW_NEEDED",
    "REBASE_REVERIFY_NEEDED",
    "MERGE_READY",
    "RECONCILE_CLOSED_PR_AND_SELECT_NEXT",
    "MULTI_ACTION",
}


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


def decide_ready_work_action(
    plan_safe: list[str],
    active_count: int,
    continuous_allowed: bool,
    unattended_slots: int,
) -> tuple[str, str, list[str]] | None:
    if not plan_safe:
        return None
    if not continuous_allowed:
        return (
            "READY_WORK_REQUIRES_AUTHORITY",
            "Planning-safe READY work exists, but current autonomy does not authorize continuous autonomous starts.",
            [],
        )
    if unattended_slots <= 0:
        return (
            "CAPACITY_BLOCKED",
            "Planning-safe READY work exists, but no verified unattended implementation route has free capacity.",
            [],
        )
    dispatchable = plan_safe[:unattended_slots]
    action = "START_PARALLEL_READY_WORK" if active_count else "START_READY_WORK"
    return (
        action,
        f"{len(dispatchable)} READY WU(s) are planning-safe and have verified unattended implementation capacity.",
        dispatchable,
    )


def dedup_and_post(repo: str, issue: int, action: str, head: str | None, detail: str) -> None:
    marker = f"<!-- onecompany-supervision:{action}:{head or 'none'} -->"
    recent = gh_json(["api", f"repos/{repo}/issues/{issue}/comments?per_page=50"])
    if any(marker in (item.get("body") or "") for item in recent):
        print("SUPERVISION: duplicate Team Room marker suppressed")
        return
    body = (
        f"{marker}\nSUPERVISION_CHECK\n\naction: {action}\nhead: {head or 'none'}\n"
        f"detail: {detail}\n\nThis is a liveness signal, not implementation progress and never renews a lease."
    )
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
    queue = load_json(CONTROL / "queue.json")
    planning = load_json(CONTROL / "planning.json")
    actors = load_json(CONTROL / "actors.json")
    readiness = load_json(CONTROL / "readiness.json")
    budget = load_json(CONTROL / "budget.json")
    dispatch = load_json(CONTROL / "dispatch.json")
    repo = github_repo_from_config(config)
    if not repo:
        print("ERROR: config.project.repository must be owner/name")
        return 2
    if not supervision.get("enabled") and not args.force_observe:
        print("SUPERVISION_DISABLED: use --force-observe for a read-only check")
        return 0
    if emergency_stop_active(config):
        print(json.dumps({
            "action": "EMERGENCY_STOP_ACTIVE",
            "detail": "Autonomous mutation is frozen; read-only diagnosis and safe containment may continue.",
            "repository": repo,
        }, indent=2))
        return 0

    try:
        prs = gh_json([
            "pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json",
            "number,title,headRefName,headRefOid,baseRefOid,isDraft,updatedAt",
        ])
    except Exception as exc:
        print(f"ERROR: cannot inspect GitHub: {exc}")
        return 2

    try:
        global_view = coordination_view()
        active = [
            item
            for item in global_view.get("active_leases", [])
            if item.get("role") == "implementation"
        ]
        durable_done = set(
            global_view.get("verified_merged_work_units", global_view.get("merged_work_units", []))
        )
    except Exception as exc:
        print(f"ERROR: cannot reconstruct coordination authority: {exc}")
        return 2

    stream_actions: list[dict] = []
    leased_prs: set[int] = set()
    threshold = int(supervision.get("continuous_operation", {}).get("stale_candidate_minutes", 30))
    for lease in active:
        pr_number = lease.get("pr")
        if not isinstance(pr_number, int):
            stream_actions.append({
                "work_unit": lease.get("work_unit"),
                "lease_id": lease.get("id"),
                "action": "RECONCILE_UNLEASED_PR",
                "detail": "Implementation lease has no PR.",
            })
            continue
        leased_prs.add(pr_number)
        try:
            live = gh_json([
                "pr", "view", str(pr_number), "--repo", repo, "--json",
                "number,title,state,headRefName,headRefOid,baseRefOid,isDraft,updatedAt,statusCheckRollup",
            ])
        except Exception:
            live = None
        if not live or live.get("state") != "OPEN":
            stream_actions.append({
                "work_unit": lease.get("work_unit"),
                "pr": pr_number,
                "action": "RECONCILE_CLOSED_PR_AND_SELECT_NEXT",
                "detail": "Leased PR is no longer open/resolvable.",
            })
            continue
        head = live.get("headRefOid")
        base = live.get("baseRefOid")
        check_state = checks_state(live.get("statusCheckRollup") or [])
        gate = coordination_view(pr_number).get("current_gate")
        if check_state == "failure":
            action, detail = "CI_REMEDIATION_NEEDED", "At least one deterministic check is failing on current head."
        elif gate and gate.get("sha") == head and gate.get("base_sha") and gate.get("base_sha") != base:
            action, detail = (
                "REBASE_REVERIFY_NEEDED",
                "Target base moved after gating; update/rebase, rerun required CI and obtain a new exact-head/base review gate.",
            )
        elif (
            check_state == "success"
            and gate
            and gate.get("sha") == head
            and gate.get("base_sha") == base
            and gate.get("verdict") == "PASS — MERGE_READY"
            and not gate.get("stale")
        ):
            action, detail = "MERGE_READY", "Green checks and trusted exact-head/base gate match the live candidate."
        elif check_state == "success":
            action, detail = "INDEPENDENT_REVIEW_NEEDED", "Checks are green but no current-head/base merge-ready gate exists."
        else:
            updated = parse_time(live.get("updatedAt"))
            if updated and dt.datetime.now(dt.timezone.utc) - updated >= dt.timedelta(minutes=threshold):
                action, detail = (
                    "RECONCILE_POSSIBLY_STALE_LEASE",
                    f"No PR-level durable activity visible in {threshold} minutes; inspect live job/branch movement before failover.",
                )
            else:
                action, detail = "ACTIVE_WORK_IN_PROGRESS", "Leased work has recent or pending deterministic activity."
        stream_actions.append({
            "work_unit": lease.get("work_unit"),
            "lease_id": lease.get("id"),
            "pr": pr_number,
            "head": head,
            "base": base,
            "expires_at": lease.get("expires_at"),
            "action": action,
            "detail": detail,
        })

    unleased_prs = [pr for pr in prs if pr.get("number") not in leased_prs]
    plan = select_parallel_set(queue.get("work_units", []), planning, active, durable_done)
    plan_safe = [str(item.get("id")) for item in plan.get("selected", []) if item.get("id")]
    unattended = implementation_pool(
        actors,
        readiness,
        budget,
        active,
        dispatch_doc=dispatch,
        require_unattended=True,
    )
    unattended_slots = int(unattended.get("free_slots", 0))

    try:
        autonomy_level = autonomy_number(config.get("autonomy", {}).get("level", "L0"))
    except ValueError:
        autonomy_level = 0
    continuous_allowed = (
        autonomy_level >= 4
        and config.get("autonomy", {}).get("continue_when_ready_work_exists") is True
    )
    ready_decision = decide_ready_work_action(plan_safe, len(active), continuous_allowed, unattended_slots)
    dispatchable_start_candidates = ready_decision[2] if ready_decision else []

    actionable_streams = [item for item in stream_actions if item.get("action") in ACTIONABLE]
    if unleased_prs:
        top_action = "RECONCILE_OPEN_PRS"
        detail = f"{len(unleased_prs)} open PR(s) are not tied to an active unexpired implementation lease."
    elif actionable_streams:
        unique = {item.get("action") for item in actionable_streams}
        top_action = next(iter(unique)) if len(unique) == 1 else "MULTI_ACTION"
        detail = f"{len(actionable_streams)} active stream transition(s) require action."
    elif ready_decision:
        top_action, detail, _ = ready_decision
    elif active:
        top_action = "ACTIVE_WORK_IN_PROGRESS"
        detail = f"{len(active)} implementation stream(s) active; no additional conflict-free slot is currently selected."
    elif any(wu.get("status") == "READY" for wu in queue.get("work_units", [])):
        top_action = "IDLE_READY_WORK_BLOCKED"
        detail = "READY work exists but dependency/conflict/WIP policy prevents a planning-safe start."
    else:
        top_action = "IDLE_NO_READY_WORK"
        detail = "No active streams and no READY WU; idle is legitimate."

    heads = sorted(str(item.get("head")) for item in stream_actions if item.get("head"))
    payload = {
        "action": top_action,
        "detail": detail,
        "repository": repo,
        "autonomy_level": f"L{autonomy_level}",
        "continuous_start_authorized": continuous_allowed,
        "stream_actions": stream_actions,
        "unleased_open_prs": [
            {
                "number": p.get("number"),
                "head": p.get("headRefOid"),
                "base": p.get("baseRefOid"),
                "branch": p.get("headRefName"),
            }
            for p in unleased_prs
        ],
        "planning_safe_start_candidates": plan_safe,
        "dispatchable_start_candidates": dispatchable_start_candidates,
        "unattended_implementation_slots": unattended_slots,
        "unattended_implementation_actors": unattended.get("actors", []),
        "active_implementation_streams": len(active),
        "expired_unreaped_streams": len(global_view.get("expired_leases", [])),
        "max_concurrent_implementation_streams": plan.get("limit"),
        "available_parallel_slots": plan.get("available_slots"),
        "durable_ledger": ledger_enabled(),
        "supervision_mode": supervision.get("mode"),
    }
    print(json.dumps(payload, indent=2))

    if args.post_team_room and top_action in ACTIONABLE:
        issue = supervision.get("coordination", {}).get("team_room_issue_number")
        if not isinstance(issue, int) or issue <= 0:
            print("ERROR: --post-team-room requires team_room_issue_number")
            return 2
        try:
            dedup_and_post(repo, issue, top_action, ",".join(heads) or None, detail)
        except Exception as exc:
            print(f"ERROR: cannot post supervision marker: {exc}")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
