#!/usr/bin/env python3
"""Mechanically merge only the exact OneCompany-approved PR head."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from onecompany_lib import CONTROL, budget_allows, command_exists, github_repo_from_config, load_json, run, save_json


def merge_actor_eligible(actor_id: str) -> tuple[bool, list[str]]:
    actors = load_json(CONTROL / "actors.json")
    readiness_doc = load_json(CONTROL / "readiness.json")
    budget = load_json(CONTROL / "budget.json")
    actor = next((item for item in actors.get("actors", []) if item.get("id") == actor_id), None)
    ready = next((item for item in readiness_doc.get("actors", []) if item.get("actor_id") == actor_id), None)
    reasons: list[str] = []
    if actor is None:
        return False, ["unknown_actor"]
    if not actor.get("enabled"):
        reasons.append("disabled")
    if not actor.get("configured"):
        reasons.append("not_configured")
    if "merge_execution" not in actor.get("capabilities", []):
        reasons.append("merge_execution_not_declared")
    if not budget_allows(actor.get("cost_class", "UNKNOWN_COST"), budget):
        reasons.append("forbidden_by_budget")
    if ready is None:
        reasons.append("missing_readiness")
    else:
        if ready.get("setup_state") not in {"ready", "degraded"}:
            reasons.append(f"setup_state:{ready.get('setup_state')}")
        if "merge_execution" not in ready.get("verified_capabilities", []):
            reasons.append("merge_execution_not_verified")
        if "merge_execution" in ready.get("temporarily_unavailable_capabilities", []):
            reasons.append("merge_execution_temporarily_unavailable")
        access = ready.get("repository_access", {})
        if not access.get("read"):
            reasons.append("repository_read_not_verified")
        if not access.get("merge"):
            reasons.append("merge_permission_not_verified")
    return not reasons, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge a PR only when the exact approved OneCompany gate remains current")
    parser.add_argument("--actor", required=True, help="Actor executing the mechanical merge")
    parser.add_argument("--method", choices=["merge", "squash", "rebase"], default="squash")
    args = parser.parse_args()

    if not command_exists("gh"):
        print("REFUSED: gh CLI is required")
        return 2
    if run(["gh", "auth", "status"]).returncode != 0:
        print("REFUSED: gh is not authenticated")
        return 2

    config = load_json(CONTROL / "config.json")
    state = load_json(CONTROL / "state.json")
    repo = github_repo_from_config(config)
    pr = state.get("current_pr")
    gate = state.get("current_gate")
    if not repo or not pr:
        print("REFUSED: repository/current_pr is not configured")
        return 2
    if not gate or gate.get("verdict") != "PASS — MERGE_READY" or gate.get("stale"):
        print("REFUSED: no current PASS — MERGE_READY gate")
        return 2
    approved_sha = gate.get("sha")
    if not approved_sha:
        print("REFUSED: gate has no approved SHA")
        return 2
    if state.get("open_blockers"):
        print("REFUSED: open blockers remain")
        return 2
    if state.get("human_decision_required"):
        print("REFUSED: human decision remains outstanding")
        return 2

    eligible, reasons = merge_actor_eligible(args.actor)
    if not eligible:
        print(f"REFUSED: merge actor {args.actor} is not eligible: {','.join(reasons)}")
        return 2

    view = run(["gh", "pr", "view", str(pr), "--repo", repo, "--json", "headRefOid,state,isDraft,mergeStateStatus"])
    if view.returncode != 0:
        print("REFUSED: cannot read live PR state")
        return 2
    live = json.loads(view.stdout)
    live_head = live.get("headRefOid")
    if live.get("state") != "OPEN" or live.get("isDraft"):
        print("REFUSED: PR is not open/ready")
        return 2
    if live_head != approved_sha or state.get("current_pr_head") != approved_sha:
        print(f"REFUSED: expected-head mismatch; approved={approved_sha} live={live_head} cached={state.get('current_pr_head')}")
        return 2

    checks = run(["gh", "pr", "checks", str(pr), "--repo", repo, "--required"])
    if checks.returncode != 0:
        print("REFUSED: required checks are not all green")
        if checks.stdout.strip():
            print(checks.stdout.strip())
        return 2
    if not checks.stdout.strip():
        print("REFUSED: no required checks were reported; autonomous merge requires deterministic required CI")
        return 2

    result = run([
        "gh", "api", "--method", "PUT", f"repos/{repo}/pulls/{pr}/merge",
        "-f", f"sha={approved_sha}",
        "-f", f"merge_method={args.method}",
    ])
    if result.returncode != 0:
        print("MERGE FAILED:", result.stderr.strip() or result.stdout.strip())
        return 2
    payload = json.loads(result.stdout)
    if not payload.get("merged"):
        print("MERGE REFUSED BY GITHUB:", payload.get("message"))
        return 2

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for lease in state.get("active_leases", []):
        if lease.get("status") == "active":
            lease["status"] = "released"
            lease["released_at"] = now
            lease["release_reason"] = "merged"
    state["last_merge"] = {
        "pr": pr,
        "approved_head": approved_sha,
        "merge_sha": payload.get("sha"),
        "actor": args.actor,
        "method": args.method,
        "merged_at": now,
    }
    state["current_work_unit"] = None
    state["current_pr"] = None
    state["current_pr_head"] = None
    state["current_material_authors"] = []
    state["current_gate"] = None
    state["company_state"] = "POST_MERGE_RECONCILE"
    save_json(CONTROL / "state.json", state)

    print(f"MERGED PR #{pr}: {payload.get('sha')} (approved exact head {approved_sha})")
    print("Next: reconcile GitHub/state and select the next dependency-ready Work Unit according to autonomy policy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
