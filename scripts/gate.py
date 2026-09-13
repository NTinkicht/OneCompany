#!/usr/bin/env python3
"""Record a binding exact-head review gate using live GitHub and the durable ledger when enabled."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from ledger_lib import derive, ledger_enabled, list_events, post_event
from onecompany_lib import CONTROL, budget_allows, command_exists, emergency_stop_active, github_repo_from_config, load_json, run, save_json

VERDICTS = ["PASS — MERGE_READY", "CHANGES_REQUIRED", "BLOCKED — CI_RED", "BLOCKED — HUMAN_DECISION", "BLOCKED — CAPACITY"]


def reviewer_eligible(actor_id: str, material_authors: set[str]) -> tuple[bool, list[str]]:
    actors = load_json(CONTROL / "actors.json")
    readiness_doc = load_json(CONTROL / "readiness.json")
    budget = load_json(CONTROL / "budget.json")
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewer", required=True); parser.add_argument("--sha", required=True)
    parser.add_argument("--verdict", required=True, choices=VERDICTS); parser.add_argument("--pr", type=int)
    parser.add_argument("--evidence", action="append", default=[]); parser.add_argument("--summary", default="")
    args = parser.parse_args()
    if emergency_stop_active():
        print("REFUSED: emergency stop is active; do not publish binding gates during containment")
        return 2
    if not command_exists("gh") or run(["gh", "auth", "status"]).returncode != 0:
        print("REFUSED: authenticated gh CLI is required"); return 2
    config = load_json(CONTROL / "config.json"); state = load_json(CONTROL / "state.json")
    repo = github_repo_from_config(config); pr = args.pr or state.get("current_pr")
    if not repo or not pr: print("REFUSED: repository and PR are required"); return 2
    view = run(["gh", "pr", "view", str(pr), "--repo", repo, "--json", "headRefOid,state,isDraft"])
    if view.returncode != 0: print("REFUSED: cannot read live PR state"); return 2
    live = json.loads(view.stdout); live_head = live.get("headRefOid")
    if live.get("state") != "OPEN" or live.get("isDraft"): print("REFUSED: binding gate requires an open non-draft PR"); return 2
    if live_head != args.sha: print(f"REFUSED: exact-head mismatch; live={live_head} reviewed={args.sha}"); return 2

    material_authors = set(state.get("current_material_authors", []))
    if ledger_enabled():
        try: material_authors = set(derive(list_events(), pr).get("material_authors", []))
        except Exception as exc: print(f"REFUSED: cannot read durable authorship ledger: {exc}"); return 2
    eligible, reasons = reviewer_eligible(args.reviewer, material_authors)
    if not eligible: print(f"REFUSED: reviewer {args.reviewer} is not eligible: {','.join(reasons)}"); return 2

    if args.verdict == "PASS — MERGE_READY":
        if not args.evidence:
            print("REFUSED: PASS — MERGE_READY requires at least one durable evidence reference")
            return 2
        if state.get("open_blockers"): print("REFUSED: open blockers remain"); return 2
        if state.get("human_decision_required"): print("REFUSED: human decision remains outstanding"); return 2
        checks = run(["gh", "pr", "checks", str(pr), "--repo", repo, "--required"])
        if checks.returncode != 0 or not checks.stdout.strip(): print("REFUSED: required PR checks are not all green/reported"); return 2

    gate = {"pr": pr, "sha": args.sha, "reviewer_actor": args.reviewer, "verdict": args.verdict, "reviewed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "material_authors": sorted(material_authors), "evidence": args.evidence, "summary": args.summary, "stale": False}
    if ledger_enabled():
        try:
            event = post_event("GATE", args.reviewer, {"pr": pr, "sha": args.sha, "verdict": args.verdict, "material_authors": sorted(material_authors), "evidence": args.evidence, "summary": args.summary})
            gate["github_comment_url"] = event.get("github_comment_url"); gate["github_publisher"] = event.get("github_publisher")
            durable = derive(list_events(), pr).get("current_gate")
            if not durable or durable.get("sha") != args.sha or durable.get("reviewer_actor") != args.reviewer or durable.get("stale"):
                print("REFUSED: newly published gate did not become a current valid durable gate")
                return 2
        except Exception as exc:
            print(f"REFUSED: durable gate publication failed: {exc}"); return 2
    state["current_pr"] = pr; state["current_pr_head"] = live_head; state["current_material_authors"] = sorted(material_authors); state["current_gate"] = gate
    state["company_state"] = "MERGE_READY" if args.verdict == "PASS — MERGE_READY" else "REVIEW_BLOCKED"
    save_json(CONTROL / "state.json", state)
    print(json.dumps(gate, indent=2)); return 0


if __name__ == "__main__": sys.exit(main())
