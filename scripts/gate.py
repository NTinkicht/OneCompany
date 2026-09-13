#!/usr/bin/env python3
"""Record a binding exact-head, base-aware review gate for one PR/Work Unit stream."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from ledger_lib import derive, ledger_enabled, list_events, post_event
from onecompany_lib import CONTROL, budget_allows, command_exists, emergency_stop_active, github_repo_from_config, load_json, run, save_json
from planning_lib import by_id
from scope_guard import changed_files, live_pr, scope_errors

VERDICTS = ["PASS — MERGE_READY", "CHANGES_REQUIRED", "BLOCKED — CI_RED", "BLOCKED — HUMAN_DECISION", "BLOCKED — CAPACITY"]


def reviewer_eligible(actor_id: str, material_authors: set[str]) -> tuple[bool, list[str]]:
    actors = load_json(CONTROL / "actors.json"); readiness_doc = load_json(CONTROL / "readiness.json"); budget = load_json(CONTROL / "budget.json")
    actor = next((item for item in actors.get("actors", []) if item.get("id") == actor_id), None)
    ready = next((item for item in readiness_doc.get("actors", []) if item.get("actor_id") == actor_id), None)
    reasons: list[str] = []
    if actor is None: return False, ["unknown_actor"]
    if actor_id in material_authors: reasons.append("material_author_conflict")
    if not actor.get("enabled"): reasons.append("disabled")
    if not actor.get("configured"): reasons.append("not_configured")
    if "code_review" not in actor.get("capabilities", []): reasons.append("code_review_not_declared")
    if actor.get("may_independently_gate_own_material_authorship") is True: reasons.append("self_gate_policy_conflict")
    if not budget_allows(actor.get("cost_class", "UNKNOWN_COST"), budget): reasons.append("forbidden_by_budget")
    if ready is None: reasons.append("missing_readiness")
    else:
        if ready.get("setup_state") not in {"ready", "degraded"}: reasons.append(f"setup_state:{ready.get('setup_state')}")
        if "code_review" not in ready.get("verified_capabilities", []): reasons.append("code_review_not_verified")
        if "code_review" in ready.get("temporarily_unavailable_capabilities", []): reasons.append("code_review_temporarily_unavailable")
        access = ready.get("repository_access", {})
        if not access.get("read"): reasons.append("repository_read_not_verified")
        if not access.get("review"): reasons.append("review_publish_not_verified")
    return not reasons, reasons


def _stream_for_pr(state: dict, pr: int) -> dict | None:
    return next((stream for stream in state.get("active_streams", []) if stream.get("pr") == pr), None)


def _work_unit_for_pr(queue: dict, state: dict, pr: int) -> dict | None:
    work = queue.get("work_units", [])
    direct = next((item for item in work if item.get("pr") == pr), None)
    if direct is not None: return direct
    stream = _stream_for_pr(state, pr)
    wu_id = (stream or {}).get("work_unit") or state.get("current_work_unit")
    return by_id(work).get(str(wu_id)) if wu_id else None


def _default_pr(state: dict) -> int | None:
    streams = [s for s in state.get("active_streams", []) if isinstance(s.get("pr"), int)]
    if len(streams) == 1: return streams[0].get("pr")
    return state.get("current_pr") if len(streams) <= 1 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewer", required=True); parser.add_argument("--sha", required=True)
    parser.add_argument("--verdict", required=True, choices=VERDICTS); parser.add_argument("--pr", type=int)
    parser.add_argument("--evidence", action="append", default=[]); parser.add_argument("--summary", default="")
    args = parser.parse_args()
    if emergency_stop_active(): print("REFUSED: emergency stop is active; do not publish binding gates during containment"); return 2
    if not command_exists("gh") or run(["gh", "auth", "status"]).returncode != 0: print("REFUSED: authenticated gh CLI is required"); return 2

    config = load_json(CONTROL / "config.json"); state = load_json(CONTROL / "state.json"); queue = load_json(CONTROL / "queue.json")
    repo = github_repo_from_config(config); pr = args.pr or _default_pr(state)
    if not repo or not pr: print("REFUSED: repository and explicit --pr are required when multiple streams are active"); return 2
    live, live_error = live_pr(repo, pr)
    if live is None: print(f"REFUSED: cannot read live PR state: {live_error}"); return 2
    live_head = live.get("headRefOid"); base_sha = live.get("baseRefOid")
    if live.get("state") != "OPEN" or live.get("isDraft"): print("REFUSED: binding gate requires an open non-draft PR"); return 2
    if live_head != args.sha: print(f"REFUSED: exact-head mismatch; live={live_head} reviewed={args.sha}"); return 2
    if not isinstance(base_sha, str) or not base_sha: print("REFUSED: live PR base SHA is unavailable"); return 2

    stream = _stream_for_pr(state, pr); work_unit = _work_unit_for_pr(queue, state, pr)
    if work_unit is None: print(f"REFUSED: PR #{pr} is not mapped to a versioned Work Unit"); return 2
    material_authors = set((stream or {}).get("material_authors", state.get("current_material_authors", [])))
    if ledger_enabled():
        try: material_authors = set(derive(list_events(), pr).get("material_authors", []))
        except Exception as exc: print(f"REFUSED: cannot read durable authorship ledger: {exc}"); return 2
    eligible, reasons = reviewer_eligible(args.reviewer, material_authors)
    if not eligible: print(f"REFUSED: reviewer {args.reviewer} is not eligible: {','.join(reasons)}"); return 2

    paths, diff_error = changed_files(repo, pr)
    if paths is None: print(f"REFUSED: cannot establish live PR change set: {diff_error}"); return 2
    scope_problems = scope_errors(paths, work_unit)

    if args.verdict == "PASS — MERGE_READY":
        if not args.evidence: print("REFUSED: PASS — MERGE_READY requires at least one durable evidence reference"); return 2
        if state.get("open_blockers"): print("REFUSED: company-wide open blockers remain"); return 2
        if state.get("human_decision_required"): print("REFUSED: company-wide human decision remains outstanding"); return 2
        if stream and stream.get("open_blockers"): print("REFUSED: stream open blockers remain"); return 2
        if stream and stream.get("human_decision_required"): print("REFUSED: stream human decision remains outstanding"); return 2
        if scope_problems:
            for problem in scope_problems: print(f"REFUSED: {problem}")
            return 2
        checks = run(["gh", "pr", "checks", str(pr), "--repo", repo, "--required"])
        if checks.returncode != 0 or not checks.stdout.strip(): print("REFUSED: required PR checks are not all green/reported"); return 2

    gate = {
        "pr": pr, "work_unit": work_unit.get("id"), "sha": args.sha, "base_sha": base_sha, "reviewer_actor": args.reviewer,
        "verdict": args.verdict, "reviewed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "material_authors": sorted(material_authors), "evidence": args.evidence, "summary": args.summary,
        "scope_verified": not scope_problems, "changed_files": paths, "stale": False,
    }
    if ledger_enabled():
        try:
            event = post_event("GATE", args.reviewer, {
                "pr": pr, "work_unit": work_unit.get("id"), "sha": args.sha, "base_sha": base_sha, "verdict": args.verdict,
                "material_authors": sorted(material_authors), "evidence": args.evidence,
                "summary": args.summary, "scope_verified": not scope_problems, "changed_files": paths,
            })
            gate["github_comment_url"] = event.get("github_comment_url"); gate["github_publisher"] = event.get("github_publisher")
            durable = derive(list_events(), pr).get("current_gate")
            if not durable or durable.get("sha") != args.sha or durable.get("base_sha") != base_sha or durable.get("reviewer_actor") != args.reviewer or durable.get("stale"):
                print("REFUSED: newly published gate did not become a current valid durable gate"); return 2
        except Exception as exc: print(f"REFUSED: durable gate publication failed: {exc}"); return 2

    matched = False
    for item in state.setdefault("active_streams", []):
        if item.get("pr") == pr:
            item.setdefault("open_blockers", []); item.setdefault("human_decision_required", False)
            item["work_unit"] = work_unit.get("id"); item["head"] = live_head; item["base_sha"] = base_sha; item["material_authors"] = sorted(material_authors); item["gate"] = gate
            item["status"] = "MERGE_READY" if args.verdict == "PASS — MERGE_READY" else "REVIEW_BLOCKED"; matched = True
    if not matched:
        state.setdefault("active_streams", []).append({
            "work_unit": work_unit.get("id"), "lease_id": "unreconciled", "actor": None,
            "branch": work_unit.get("branch"), "pr": pr, "head": live_head, "base_sha": base_sha, "material_authors": sorted(material_authors),
            "gate": gate, "status": "MERGE_READY" if args.verdict == "PASS — MERGE_READY" else "REVIEW_BLOCKED",
            "open_blockers": [], "human_decision_required": False,
        })
    if len(state.get("active_streams", [])) == 1:
        state["current_work_unit"] = work_unit.get("id"); state["current_pr"] = pr; state["current_pr_head"] = live_head; state["current_material_authors"] = sorted(material_authors); state["current_gate"] = gate
    else:
        state["current_work_unit"] = None; state["current_pr"] = None; state["current_pr_head"] = None; state["current_material_authors"] = []; state["current_gate"] = None
    state["company_state"] = "MERGE_READY" if len(state.get("active_streams", [])) == 1 and args.verdict == "PASS — MERGE_READY" else ("ACTIVE_PARALLEL_IMPLEMENTATION" if len(state.get("active_streams", [])) > 1 else "REVIEW_BLOCKED")
    save_json(CONTROL / "state.json", state)
    print(json.dumps(gate, indent=2)); return 0


if __name__ == "__main__":
    sys.exit(main())
