#!/usr/bin/env python3
"""Record an exact-head/base review gate from platform identity and coordination truth."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from lease_lifecycle import append_coordination_event, coordination_view
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


def _active_implementation(view: dict, pr: int) -> list[dict]:
    return [
        lease
        for lease in view.get("active_leases", [])
        if lease.get("role") == "implementation" and lease.get("pr") == pr
    ]


def _default_pr(global_view: dict) -> int | None:
    values = sorted(
        {
            lease.get("pr")
            for lease in global_view.get("active_leases", [])
            if lease.get("role") == "implementation"
            and isinstance(lease.get("pr"), int)
        }
    )
    return values[0] if len(values) == 1 else None


def _work_unit_for_pr(queue: dict, pr: int, active: list[dict]) -> dict | None:
    work = queue.get("work_units", [])
    direct = next((item for item in work if item.get("pr") == pr), None)
    if direct is not None:
        return direct
    lease = next((item for item in active if item.get("work_unit")), None)
    wu_id = (lease or {}).get("work_unit")
    return by_id(work).get(str(wu_id)) if wu_id else None


def _live_context(repo: str, pr: int, reviewed_sha: str) -> tuple[dict | None, str | None]:
    live, error = live_pr(repo, pr)
    if live is None:
        return None, f"cannot read live PR state: {error}"
    live_head = live.get("headRefOid")
    base_sha = live.get("baseRefOid")
    if live.get("state") != "OPEN" or live.get("isDraft"):
        return None, "binding gate requires an open non-draft PR"
    if live_head != reviewed_sha:
        return None, f"exact-head mismatch; live={live_head} reviewed={reviewed_sha}"
    if not isinstance(base_sha, str) or not base_sha:
        return None, "live PR base SHA is unavailable"
    return live, None


def _pass_preconditions(
    repo: str,
    candidate_sha: str,
    base_sha: str,
    evidence: list[str],
    state: dict,
    cached_stream: dict | None,
    scope_problems: list[str],
) -> tuple[list[str], list[dict]]:
    errors: list[str] = []
    required_check_evidence: list[dict] = []
    if not evidence:
        errors.append("PASS — MERGE_READY requires at least one durable evidence reference")

    # State is cache-only. It may add a blocker, but it never grants authority.
    if state.get("open_blockers"):
        errors.append("company-wide open blockers remain")
    if state.get("human_decision_required"):
        errors.append("company-wide human decision remains outstanding")
    if cached_stream and cached_stream.get("open_blockers"):
        errors.append("cached stream blockers remain")
    if cached_stream and cached_stream.get("human_decision_required"):
        errors.append("cached stream human decision remains outstanding")

    errors.extend(scope_problems)
    checks_ok, check_reasons, required_check_evidence = evaluate_required_checks(
        repo,
        candidate_sha,
        trusted_ref=base_sha,
    )
    if not checks_ok:
        errors.extend(check_reasons)
    return errors, required_check_evidence


def _cache_gate(
    state: dict,
    gate: dict,
    work_unit: dict,
    live_head: str,
    base_sha: str,
    material_authors: set[str],
) -> None:
    pr = gate["pr"]
    matched = False
    for item in state.setdefault("active_streams", []):
        if item.get("pr") != pr:
            continue
        item.setdefault("open_blockers", [])
        item.setdefault("human_decision_required", False)
        item.update(
            {
                "work_unit": work_unit.get("id"),
                "head": live_head,
                "base_sha": base_sha,
                "material_authors": sorted(material_authors),
                "gate": gate,
                "status": (
                    "MERGE_READY"
                    if gate["verdict"] == "PASS — MERGE_READY"
                    else "REVIEW_BLOCKED"
                ),
            }
        )
        matched = True

    if not matched:
        state.setdefault("active_streams", []).append(
            {
                "work_unit": work_unit.get("id"),
                "lease_id": "cache-only",
                "actor": None,
                "branch": work_unit.get("branch"),
                "pr": pr,
                "head": live_head,
                "base_sha": base_sha,
                "material_authors": sorted(material_authors),
                "gate": gate,
                "status": (
                    "MERGE_READY"
                    if gate["verdict"] == "PASS — MERGE_READY"
                    else "REVIEW_BLOCKED"
                ),
                "open_blockers": [],
                "human_decision_required": False,
            }
        )

    streams = state.get("active_streams", [])
    if len(streams) == 1:
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

    if len(streams) == 1 and gate["verdict"] == "PASS — MERGE_READY":
        state["company_state"] = "MERGE_READY"
    elif len(streams) > 1:
        state["company_state"] = "ACTIVE_PARALLEL_IMPLEMENTATION"
    else:
        state["company_state"] = "REVIEW_BLOCKED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--review-id",
        type=int,
        required=True,
        help="GitHub pull-request review ID",
    )
    parser.add_argument(
        "--reviewer",
        help=(
            "Optional descriptive assertion; must match the platform-derived "
            "login or actor ID"
        ),
    )
    parser.add_argument("--sha", required=True)
    parser.add_argument("--verdict", required=True, choices=VERDICTS)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--summary", default="")
    args = parser.parse_args()

    if emergency_stop_active():
        print(
            "REFUSED: emergency stop is active; do not publish binding gates "
            "during containment"
        )
        return 2
    if not command_exists("gh") or run(["gh", "auth", "status"]).returncode != 0:
        print("REFUSED: authenticated gh CLI is required")
        return 2

    config = load_json(CONTROL / "config.json")
    state = load_json(CONTROL / "state.json")
    queue = load_json(CONTROL / "queue.json")
    repo = github_repo_from_config(config)

    try:
        global_view = coordination_view()
    except Exception as exc:
        print(f"REFUSED: cannot reconstruct coordination authority: {exc}")
        return 2

    pr = args.pr or _default_pr(global_view)
    if not repo or not pr:
        print(
            "REFUSED: repository and explicit --pr are required when zero or "
            "multiple implementation streams are active"
        )
        return 2

    live, live_error = _live_context(repo, pr, args.sha)
    if live is None:
        print(f"REFUSED: {live_error}")
        return 2
    live_head = str(live.get("headRefOid"))
    base_sha = str(live.get("baseRefOid"))

    try:
        view = coordination_view(pr)
    except Exception as exc:
        print(f"REFUSED: cannot reconstruct PR coordination authority: {exc}")
        return 2

    active = _active_implementation(view, pr)
    if not active:
        print("REFUSED: PR has no canonical active unexpired implementation lease")
        return 2

    work_unit = _work_unit_for_pr(queue, pr, active)
    if work_unit is None:
        print(f"REFUSED: PR #{pr} is not mapped to a versioned Work Unit")
        return 2

    material_authors = set(view.get("material_authors", []))
    allowed_states = (
        {"APPROVED"}
        if args.verdict == "PASS — MERGE_READY"
        else NON_PASS_REVIEW_STATES
    )
    reviewer_identity, identity_errors = review_platform_identity(
        repo,
        pr,
        args.review_id,
        args.sha,
        base_sha,
        allowed_states=allowed_states,
    )
    if reviewer_identity is None:
        print(
            "REFUSED: platform reviewer identity is not verified: "
            + ",".join(identity_errors)
        )
        return 2

    reviewer_ok, reviewer_reasons = require_authority(
        reviewer_identity,
        "code_review",
        material_authors,
    )
    if not reviewer_ok:
        print(
            "REFUSED: platform reviewer lacks independent code-review authority: "
            + ",".join(reviewer_reasons)
        )
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

    cached_stream = next(
        (item for item in state.get("active_streams", []) if item.get("pr") == pr),
        None,
    )
    required_check_evidence: list[dict] = []
    if args.verdict == "PASS — MERGE_READY":
        problems, required_check_evidence = _pass_preconditions(
            repo,
            args.sha,
            base_sha,
            args.evidence,
            state,
            cached_stream,
            scope_problems,
        )
        if problems:
            for problem in problems:
                print(f"REFUSED: {problem}")
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
    try:
        event = append_coordination_event("GATE", reviewer_actor, payload)
        gate["github_comment_url"] = event.get("github_comment_url")
        gate["github_publisher"] = event.get("github_publisher")
        durable = coordination_view(pr).get("current_gate")
    except Exception as exc:
        print(f"REFUSED: binding gate publication failed: {exc}")
        return 2

    if (
        not durable
        or durable.get("sha") != args.sha
        or durable.get("base_sha") != base_sha
        or durable.get("reviewer_actor") != reviewer_actor
        or durable.get("review_id") != args.review_id
        or durable.get("stale")
    ):
        print("REFUSED: newly published gate did not become the current valid gate")
        return 2

    # Cache mirrors coordination truth for UX only.
    _cache_gate(
        state,
        gate,
        work_unit,
        live_head,
        base_sha,
        material_authors,
    )
    save_json(CONTROL / "state.json", state)
    print(json.dumps(gate, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
