#!/usr/bin/env python3
"""Validate the continuous-supervision policy without requiring network access."""
from __future__ import annotations

import sys

from onecompany_lib import CONTROL, autonomy_number, load_json


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    supervision = load_json(CONTROL / "supervision.json")
    config = load_json(CONTROL / "config.json")
    budget = load_json(CONTROL / "budget.json")

    if supervision.get("mode") not in {"observe_only", "notify", "orchestrate"}:
        errors.append("supervision.mode must be observe_only, notify or orchestrate")

    continuous = supervision.get("continuous_operation", {})
    for key in ("event_driven_first", "scheduled_reconciliation", "quiet_when_no_action"):
        if continuous.get(key) is not True:
            errors.append(f"supervision.continuous_operation.{key} must be true in the reference model")
    for key in ("stale_candidate_minutes", "target_effective_cadence_minutes"):
        value = continuous.get(key)
        if not isinstance(value, int) or value < 5:
            errors.append(f"supervision.continuous_operation.{key} must be an integer >= 5")

    safety = supervision.get("safety", {})
    required_true = (
        "scheduler_is_supervisor_not_implementer",
        "must_reconcile_live_github_before_action",
        "must_verify_no_deterministic_job_progress_before_failover",
        "never_create_duplicate_implementation_stream",
        "never_override_budget_policy",
        "never_override_human_only_decisions",
    )
    for key in required_true:
        if safety.get(key) is not True:
            errors.append(f"supervision.safety.{key} must be true")

    try:
        level = autonomy_number(config.get("autonomy", {}).get("level", "L0"))
        merge_min = autonomy_number(safety.get("automatic_merge_minimum_autonomy_level", "L3"))
        next_min = autonomy_number(safety.get("automatic_next_work_minimum_autonomy_level", "L4"))
    except ValueError as exc:
        errors.append(str(exc))
        level = merge_min = next_min = 0

    if merge_min < 3:
        errors.append("automatic merge minimum autonomy must be L3 or higher")
    if next_min < 4:
        errors.append("automatic next-work minimum autonomy must be L4 or higher")
    if supervision.get("enabled") and supervision.get("mode") == "orchestrate" and level < 3:
        errors.append("orchestrating supervision requires autonomy L3+ in the reference model")
    if level >= 4 and config.get("autonomy", {}).get("continue_when_ready_work_exists") and not supervision.get("enabled"):
        warnings.append("L4+ continuous queue is enabled while supervision.enabled=false; ensure an equivalent external liveness mechanism exists")

    gh = supervision.get("github_actions", {})
    if gh.get("enabled") and continuous.get("target_effective_cadence_minutes", 60) < 60:
        if not budget.get("ci", {}).get("allow_high_frequency_scheduled_watchdogs"):
            errors.append("high-frequency GitHub Actions supervision is enabled but budget.ci.allow_high_frequency_scheduled_watchdogs=false")
    if gh.get("may_failover") or gh.get("may_merge"):
        warnings.append("GitHub Actions supervisor has mutation authority; verify L3+, least privilege and first-run drills")

    chatgpt = supervision.get("chatgpt_tasks", {})
    offsets = chatgpt.get("offset_minutes", [])
    if not isinstance(offsets, list) or not offsets:
        errors.append("supervision.chatgpt_tasks.offset_minutes must be a non-empty list")
    else:
        if any(not isinstance(v, int) or v < 0 or v > 59 for v in offsets):
            errors.append("ChatGPT supervisor offsets must be integer minutes 0..59")
        if len(offsets) != len(set(offsets)):
            errors.append("ChatGPT supervisor offsets must be unique")
        if chatgpt.get("strategy") == "four_staggered_hourly_supervisors" and len(offsets) != 4:
            errors.append("four_staggered_hourly_supervisors requires exactly four offsets")
    if chatgpt.get("may_mutate") and supervision.get("mode") != "orchestrate":
        errors.append("ChatGPT scheduled tasks may mutate only when supervision.mode=orchestrate")

    issue = supervision.get("coordination", {}).get("team_room_issue_number")
    if issue is not None and (not isinstance(issue, int) or issue <= 0):
        errors.append("supervision.coordination.team_room_issue_number must be null or a positive integer")

    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"OneCompany supervision validation FAILED ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1
    print(f"OneCompany supervision validation PASS ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
