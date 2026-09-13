#!/usr/bin/env python3
"""Record a binding exact-head/base gate backed by an exact GitHub review."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from ledger_lib import derive, ledger_enabled, list_events, post_event
from onecompany_lib import (
    CONTROL,
    command_exists,
    emergency_stop_active,
    github_repo_from_config,
    load_json,
    run,
    save_json,
)
from planning_lib import by_id
from platform_identity import require_authority, review_platform_identity
from required_checks import evaluate_required_checks
from scope_guard import changed_files, live_pr, scope_errors

VERDICTS = [
    "PASS — MERGE_READY",
    "CHANGES_REQUIRED",
    "BLOCKED — CI_RED",
    "BLOCKED — HUMAN_DECISION",
    "BLOCKED — CAPACITY",
]
NON_PASS_REVIEW_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}


def _stream_for_pr(state: dict, pr: int) -> dict | None:
    return next((stream for stream in state.get("active_streams", []) if stream.get("pr") == pr), None)


def _work_unit_for_pr(queue: dict, state: dict, pr: int) -> dict | None:
    work = queue.get("work_units", [])
    direct = next((item for item in work if item.get("pr") == pr), None)
    if direct is not None:
        return direct
    stream = _stream_for_pr(state, pr)
    wu_id = (stream or {}).get("work_unit") or state.get("current_work_unit")
    return by_id(work).get(str(wu_id)) if wu_id else None


def _default_pr(state: dict) -> int | None:
    streams = [s for s in state.get("active_streams", []) if isinstance(s.get("pr"), int)]
    if len(streams) == 1:
        return streams[0].get("pr")
    return state.get("current_pr") if len(streams) <= 1 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-id", type=int, required=True, help="GitHub pull-request review ID")
    parser.add_argument(
        "--reviewer",
        help="Optional descriptive assertion; must match the platform-derived login or actor ID",
    )
    parser.add_argument("--sha", required=True)
    parser.add_argument("--verdict", required=True, choices=VERDICTS)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--summary", default="")
    args = parser.parse_args()

    if emergency_stop_active():
        print("REFUSED: emergency stop is active; do not publish binding gates during containment")
        return 2
    if not command_exists("gh") or run(["gh", "auth", "status"]).returncode != 0:
        print("REFUSED: authenticated gh CLI is required")
        return 2

    config = load_json(CONTROL / "config.json")
    state = load_json(CONTROL / "state.json")
    queue = load_json(CONTROL / "queue.json")
    repo = github_repo_from_config(config)
    pr = args.pr or _default_pr(state)
    if not repo or not pr:
        print("REFUSED: repository and explicit --pr are required when multiple streams are active")
        return 2

    live, live_error = live_pr(repo, pr)
    if live is None:
        print(f"REFUSED: cannot read live PR state: {live_error}")
        return 2
    live_head = live.get("headRefOid")
    base_sha = live.get("baseRefOid")
    if live.get("state") != "OPEN" or live.get("isDraft"):
        print("REFUSED: binding gate requires an open non-draft PR")
        return 2
    if live_head != args.sha:
        print(f"REFUSED: exact-head mismatch; live={live_head} reviewed={args.sha}")
        return 2
    if not isinstance(base_sha, str) or not base_sha:
        print("REFUSED: live PR base SHA is unavailable")
        return 2

    stream = _stream_for_pr(state, pr)
    work_unit = _work_unit_for_pr(queue, state, pr)
    if work_unit is None:
        print(f"REFUSED: PR #{pr} is not mapped to a versioned Work Unit")
        return 2

    material_authors = set(
        (stream or {}).get("material_authors", state.get("current_material_authors", []))
    )
    if ledger_enabled():
        try:
            material_authors = set(derive(list_events(), pr).get("material_authors", []))
        except Exception as exc:
            print(f"REFUSED: cannot read durable authorship ledger: {exc}")
            return 2

    allowed_states = {"APPROVED"} if args.verdict == "PASS — MERGE_READY" else NON_PASS_REVIEW_STATES
    reviewer_identity, identity_errors = review_platform_identity(
        repo,
        pr,
        args.review_id,
        args.sha,
        base_sha,
        allowed_states=allowed_states,
    )
    if reviewer_identity is None:
        print("REFUSED: platform reviewer identity is not verified: " + ",".join(identity_errors))
        return 2
    reviewer_ok, reviewer_reasons = require_authority(
        reviewer_identity,
        "code_review",
        material_authors,
    )
    if not reviewer_ok:
        print("REFUSED: platform reviewer lacks independent code-review authority: " + ",".join(reviewer_reasons))
        return 2
    reviewer_actor = str(reviewer_identity.get("actor_id"))
    reviewer_login = str(reviewer_identity.get("login"))
    if args.reviewer and args.reviewer not in {reviewer_actor, reviewer_login}:
        print(
            f"REFUSED: descriptive --reviewer {args.reviewer!r} does not match "
            f"platform identity actor={reviewer_actor!r} login={reviewer_login!r}"
        )
        return 2

    paths, diff_error = changed_files(repo, pr)
    if paths is None:
        print(f"REFUSED: cannot establish live PR change set: {diff_error}")
        return 2
    scope_problems = scope_errors(paths, work_unit)
    required_check_evidence: list[dict] = []

    if args.verdict == "PASS — MERGE_READY":
        if not args.evidence:
            print("REFUSED: PASS — MERGE_READY requires at least one durable evidence reference")
            return 2
        if state.get("open_blockers") or (stream and stream.get("open_blockers")):
            print("REFUSED: open blockers remain")
            return 2
        if state.get("human_decision_required") or (stream and stream.get("human_decision_required")):
            print("REFUSED: human decision remains outstanding")
            return 2
        if scope_problems:
            for problem in scope_problems:
                print(f"REFUSED: {problem}")
            return 2
        checks_ok, check_reasons, required_check_evidence = evaluate_required_checks(
            repo, args.sha, trusted_ref=base_sha
        )
        if not checks_ok:
            for reason in check_reasons:
                print(f"REFUSED: {reason}")
            return 2

    review_record = {
        "review_id": args.review_id,
        "reviewer_login": reviewer_login,
        "reviewer_actor": reviewer_actor,
        "review_state": reviewer_identity.get("review_state"),
        "review_commit_id": reviewer_identity.get("review_commit_id"),
        "identity_provider": reviewer_identity.get("provider"),
        "identity_policy_provenance": reviewer_identity.get("policy_provenance"),
        "bootstrap_review_only": reviewer_identity.get("bootstrap_review_only") is True,
    }
    gate = {
        "pr": pr,
        "work_unit": work_unit.get("id"),
        "sha": args.sha,
        "base_sha": base_sha,
        "reviewer_actor": reviewer_actor,
        "reviewer_login": reviewer_login,
        "review_id": args.review_id,
        "review_identity": review_record,
        "verdict": args.verdict,
        "reviewed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "material_authors": sorted(material_authors),
        "evidence": args.evidence,
        "required_checks": required_check_evidence,
        "summary": args.summary,
        "scope_verified": not scope_problems,
        "changed_files": paths,
        "stale": False,
    }

    if ledger_enabled():
        try:
            payload = {
                "pr": pr,
                "work_unit": work_unit.get("id"),
                "sha": args.sha,
                "base_sha": base_sha,
                "review_id": args.review_id,
                "reviewer_login": reviewer_login,
                "review_identity": review_record,
                "verdict": args.verdict,
                "material_authors": sorted(material_authors),
                "evidence": args.evidence,
                "required_checks": required_check_evidence,
                "summary": args.summary,
                "scope_verified": not scope_problems,
                "changed_files": paths,
            }
            event = post_event("GATE", reviewer_actor, payload)
            gate["github_comment_url"] = event.get("github_comment_url")
            gate["github_publisher"] = event.get("github_publisher")
            durable = derive(list_events(), pr).get("current_gate")
            if (
                not durable
                or durable.get("sha") != args.sha
                or durable.get("base_sha") != base_sha
                or durable.get("reviewer_actor") != reviewer_actor
                or durable.get("review_id") != args.review_id
                or durable.get("stale")
            ):
                print("REFUSED: newly published gate did not become a current valid durable gate")
                return 2
        except Exception as exc:
            print(f"REFUSED: durable gate publication failed: {exc}")
            return 2

    matched = False
    for item in state.setdefault("active_streams", []):
        if item.get("pr") == pr:
            item.setdefault("open_blockers", [])
            item.setdefault("human_decision_required", False)
            item.update(
                {
                    "work_unit": work_unit.get("id"),
                    "head": live_head,
                    "base_sha": base_sha,
                    "material_authors": sorted(material_authors),
                    "gate": gate,
                    "status": "MERGE_READY" if args.verdict == "PASS — MERGE_READY" else "REVIEW_BLOCKED",
                }
            )
            matched = True
    if not matched:
        state.setdefault("active_streams", []).append(
            {
                "work_unit": work_unit.get("id"),
                "lease_id": "unreconciled",
                "actor": None,
                "branch": work_unit.get("branch"),
                "pr": pr,
                "head": live_head,
                "base_sha": base_sha,
                "material_authors": sorted(material_authors),
                "gate": gate,
                "status": "MERGE_READY" if args.verdict == "PASS — MERGE_READY" else "REVIEW_BLOCKED",
                "open_blockers": [],
                "human_decision_required": False,
            }
        )
    if len(state.get("active_streams", [])) == 1:
        state["current_work_unit"] = work_unit.get("id")
        state["current_pr"] = pr
        state["current_pr_head"] = live_head
        state["current_material_authors"] = sorted(material_authors)
        state["current_gate"] = gate
    else:
        state["current_work_unit"] = None
        state["current_pr"] = None
        state["current_pr_head"] = None
        state["current_material_authors"] = []
        state["current_gate"] = None
    state["company_state"] = (
        "MERGE_READY"
        if len(state.get("active_streams", [])) == 1 and args.verdict == "PASS — MERGE_READY"
        else ("ACTIVE_PARALLEL_IMPLEMENTATION" if len(state.get("active_streams", [])) > 1 else "REVIEW_BLOCKED")
    )
    save_json(CONTROL / "state.json", state)
    print(json.dumps(gate, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
