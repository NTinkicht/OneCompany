#!/usr/bin/env python3
"""Mechanically merge only the exact live, independently approved OneCompany PR head."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from ledger_lib import derive, ledger_config, ledger_enabled, list_events, post_event
from onecompany_lib import (
    CONTROL, always_human_paths, autonomy_number, budget_allows, command_exists,
    emergency_stop_active, github_repo_from_config, governance_config, load_json,
    protected_control_plane_paths, run, save_json,
)


def capability_eligible(actor_id: str, capability: str, access_key: str, excluded_authors: set[str] | None = None) -> tuple[bool, list[str]]:
    actors = load_json(CONTROL / "actors.json"); readiness_doc = load_json(CONTROL / "readiness.json"); budget = load_json(CONTROL / "budget.json")
    actor = next((item for item in actors.get("actors", []) if item.get("id") == actor_id), None)
    ready = next((item for item in readiness_doc.get("actors", []) if item.get("actor_id") == actor_id), None)
    reasons: list[str] = []
    if actor is None: return False, ["unknown_actor"]
    if excluded_authors and actor_id in excluded_authors: reasons.append("material_author_conflict")
    if not actor.get("enabled"): reasons.append("disabled")
    if not actor.get("configured"): reasons.append("not_configured")
    if capability not in actor.get("capabilities", []): reasons.append(f"{capability}_not_declared")
    if not budget_allows(actor.get("cost_class", "UNKNOWN_COST"), budget): reasons.append("forbidden_by_budget")
    if ready is None: reasons.append("missing_readiness")
    else:
        if ready.get("setup_state") not in {"ready", "degraded"}: reasons.append(f"setup_state:{ready.get('setup_state')}")
        if capability not in ready.get("verified_capabilities", []): reasons.append(f"{capability}_not_verified")
        if capability in ready.get("temporarily_unavailable_capabilities", []): reasons.append(f"{capability}_temporarily_unavailable")
        access = ready.get("repository_access", {})
        if not access.get("read"): reasons.append("repository_read_not_verified")
        if not access.get(access_key): reasons.append(f"repository_{access_key}_not_verified")
    return not reasons, reasons


def changed_files(repo: str, pr: int) -> tuple[list[str] | None, str | None]:
    result = run(["gh", "pr", "diff", str(pr), "--repo", repo, "--name-only"])
    if result.returncode != 0: return None, result.stderr.strip() or result.stdout.strip() or "unknown diff error"
    return [line.strip() for line in result.stdout.splitlines() if line.strip()], None


def _stream_for_pr(state: dict, pr: int) -> dict | None:
    return next((stream for stream in state.get("active_streams", []) if stream.get("pr") == pr), None)


def _default_pr(state: dict) -> int | None:
    streams = [s for s in state.get("active_streams", []) if isinstance(s.get("pr"), int)]
    if len(streams) == 1: return streams[0].get("pr")
    return state.get("current_pr") if len(streams) <= 1 else None


def _sync_legacy(state: dict) -> None:
    streams = state.get("active_streams", [])
    if len(streams) == 1:
        stream = streams[0]
        state["current_work_unit"] = stream.get("work_unit"); state["current_pr"] = stream.get("pr")
        state["current_pr_head"] = stream.get("head"); state["current_material_authors"] = stream.get("material_authors", [])
        state["current_gate"] = stream.get("gate")
    else:
        state["current_work_unit"] = None; state["current_pr"] = None; state["current_pr_head"] = None
        state["current_material_authors"] = []; state["current_gate"] = None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", required=True); parser.add_argument("--pr", type=int)
    parser.add_argument("--method", choices=["merge", "squash", "rebase"], default="squash")
    args = parser.parse_args()
    if emergency_stop_active(): print("REFUSED: emergency stop is active; autonomous merge is frozen"); return 2
    if not command_exists("gh") or run(["gh", "auth", "status"]).returncode != 0: print("REFUSED: authenticated gh CLI is required"); return 2

    config = load_json(CONTROL / "config.json"); state = load_json(CONTROL / "state.json")
    repo = github_repo_from_config(config); pr = args.pr or _default_pr(state)
    if not repo or not pr: print("REFUSED: repository/explicit --pr is required when multiple streams are active"); return 2
    try: level = autonomy_number(config.get("autonomy", {}).get("level", "L0"))
    except ValueError as exc: print(f"REFUSED: {exc}"); return 2
    if level >= 3 and ledger_config().get("required_for_autonomous_merge") and not ledger_enabled(): print("REFUSED: L3+ autonomous merge requires durable ledger"); return 2

    paths, diff_error = changed_files(repo, pr); governance = governance_config().get("control_plane", {})
    if paths is None:
        if governance.get("fail_closed_if_diff_unavailable", True): print(f"REFUSED: cannot establish PR change set for governance check: {diff_error}"); return 2
        paths = []
    protected = protected_control_plane_paths(paths); absolute_human = always_human_paths(paths)
    if absolute_human and args.actor != "human-owner": print(f"REFUSED: always-human governance paths changed: {', '.join(absolute_human)}"); return 2
    if protected and governance.get("human_merge_required") is True and args.actor != "human-owner": print(f"REFUSED: protected control-plane change requires human-owner merge: {', '.join(protected)}"); return 2

    stream = _stream_for_pr(state, pr)
    gate = (stream or {}).get("gate", state.get("current_gate"))
    active = [lease for lease in state.get("active_leases", []) if lease.get("status") == "active" and lease.get("role") == "implementation" and lease.get("pr") == pr]
    material_authors = set((stream or {}).get("material_authors", state.get("current_material_authors", [])))
    if ledger_enabled():
        try:
            view = derive(list_events(), pr); gate = view.get("current_gate"); active = view.get("active_leases", []); material_authors = set(view.get("material_authors", []))
        except Exception as exc: print(f"REFUSED: cannot read durable ledger: {exc}"); return 2
    if not gate or gate.get("verdict") != "PASS — MERGE_READY" or gate.get("stale"): print("REFUSED: no current durable PASS — MERGE_READY gate"); return 2
    if set(gate.get("material_authors") or []) != material_authors: print("REFUSED: gate authorship snapshot differs from current durable authorship"); return 2
    reviewer = gate.get("reviewer_actor")
    if not isinstance(reviewer, str) or not reviewer: print("REFUSED: gate has no reviewer actor"); return 2
    reviewer_ok, reviewer_reasons = capability_eligible(reviewer, "code_review", "review", material_authors)
    if not reviewer_ok: print(f"REFUSED: gate reviewer is no longer independently eligible: {','.join(reviewer_reasons)}"); return 2
    if not gate.get("evidence"): print("REFUSED: merge-ready gate has no durable evidence reference"); return 2
    approved_sha = gate.get("sha")
    if not approved_sha: print("REFUSED: gate has no approved SHA"); return 2
    if state.get("open_blockers"): print("REFUSED: open blockers remain"); return 2
    if state.get("human_decision_required"): print("REFUSED: human decision remains outstanding"); return 2
    merge_ok, merge_reasons = capability_eligible(args.actor, "merge_execution", "merge")
    if not merge_ok: print(f"REFUSED: merge actor {args.actor} is not eligible: {','.join(merge_reasons)}"); return 2

    result = run(["gh", "pr", "view", str(pr), "--repo", repo, "--json", "headRefOid,state,isDraft,mergeStateStatus"])
    if result.returncode != 0: print("REFUSED: cannot read live PR state"); return 2
    live = json.loads(result.stdout); live_head = live.get("headRefOid")
    if live.get("state") != "OPEN" or live.get("isDraft"): print("REFUSED: PR is not open/ready"); return 2
    if live_head != approved_sha: print(f"REFUSED: expected-head mismatch; approved={approved_sha} live={live_head}"); return 2
    checks = run(["gh", "pr", "checks", str(pr), "--repo", repo, "--required"])
    if checks.returncode != 0 or not checks.stdout.strip(): print("REFUSED: required checks are not all green/reported"); return 2

    merge = run(["gh", "api", "--method", "PUT", f"repos/{repo}/pulls/{pr}/merge", "-f", f"sha={approved_sha}", "-f", f"merge_method={args.method}"])
    if merge.returncode != 0: print("MERGE FAILED:", merge.stderr.strip() or merge.stdout.strip()); return 2
    payload = json.loads(merge.stdout)
    if not payload.get("merged"): print("MERGE REFUSED BY GITHUB:", payload.get("message")); return 2

    work_unit = (stream or {}).get("work_unit") or next((item.get("work_unit") for item in active if item.get("work_unit")), None)
    if ledger_enabled():
        try:
            for lease in active: post_event("ROLE_LEASE_RELEASED", str(lease.get("actor") or args.actor), {"lease_id": lease.get("id"), "pr": pr, "reason": "merged"})
            post_event("MERGED", args.actor, {"pr": pr, "work_unit": work_unit, "approved_head": approved_sha, "merge_sha": payload.get("sha"), "method": args.method})
        except Exception as exc:
            print(f"WARN: merge succeeded but ledger post-merge record failed: {exc}")

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for lease in state.get("active_leases", []):
        if lease.get("status") == "active" and lease.get("role") == "implementation" and lease.get("pr") == pr:
            lease["status"] = "released"; lease["released_at"] = now; lease["release_reason"] = "merged"
    state["active_streams"] = [item for item in state.get("active_streams", []) if item.get("pr") != pr]
    state["last_merge"] = {"pr": pr, "work_unit": work_unit, "approved_head": approved_sha, "merge_sha": payload.get("sha"), "actor": args.actor, "method": args.method, "merged_at": now}
    _sync_legacy(state)
    state["company_state"] = "ACTIVE_PARALLEL_IMPLEMENTATION" if len(state.get("active_streams", [])) > 1 else ("ACTIVE_IMPLEMENTATION" if state.get("active_streams") else "POST_MERGE_RECONCILE")
    save_json(CONTROL / "state.json", state)
    print(f"MERGED PR #{pr}: {payload.get('sha')} (approved exact head {approved_sha})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
