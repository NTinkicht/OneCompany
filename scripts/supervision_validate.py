#!/usr/bin/env python3
"""Validate continuous-supervision policy without requiring network access."""
from __future__ import annotations

import sys
from pathlib import Path

from onecompany_lib import CONTROL, ROOT, autonomy_number, load_json


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
            errors.append(f"supervision.continuous_operation.{key} must be true")
    for key in ("stale_candidate_minutes", "target_effective_cadence_minutes"):
        value = continuous.get(key)
        if not isinstance(value, int) or value < 5:
            errors.append(f"supervision.continuous_operation.{key} must be an integer >= 5")

    safety = supervision.get("safety", {})
    for key in (
        "scheduler_is_supervisor_not_implementer",
        "must_reconcile_live_github_before_action",
        "must_verify_no_deterministic_job_progress_before_failover",
        "never_create_duplicate_implementation_stream",
        "never_override_budget_policy",
        "never_override_human_only_decisions",
    ):
        if safety.get(key) is not True:
            errors.append(f"supervision.safety.{key} must be true")

    health = supervision.get("scheduler_health", {})
    for key in (
        "verify_active_daily",
        "scheduler_failure_must_be_visible",
        "do_not_depend_on_exact_cron_timing",
        "scheduled_task_project_files_are_not_assumed_available",
    ):
        if health.get(key) is not True:
            errors.append(f"supervision.scheduler_health.{key} must be true")

    liveness = supervision.get("liveness_policy", {})
    for key in (
        "stale_suspicion_never_grants_failover",
        "progress_required_for_renewal",
        "reconcile_before_failover",
        "deduplicate_supervisor_replicas",
        "autonomy_gate_before_mutation",
        "read_only_actions_allowed_at_l1",
    ):
        if liveness.get(key) is not True:
            errors.append(f"supervision.liveness_policy.{key} must be true")
    if liveness.get("write_failover_minimum_autonomy_level") != "L3":
        errors.append("write failover minimum autonomy must remain L3")

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
        errors.append("orchestrating supervision requires autonomy L3+")

    gh = supervision.get("github_actions", {})
    if supervision.get("enabled") is not True:
        errors.append("B3 active supervision must be enabled")
    if level == 1:
        if supervision.get("mode") != "notify":
            errors.append("L1 B3 supervision must remain notify-only")
        if gh.get("enabled") is not True:
            errors.append("L1 B3 requires GitHub Actions reconciliation enabled")
        if gh.get("may_post_team_room") is not True:
            errors.append("L1 B3 should expose actionable liveness signals in Team Room")
        if gh.get("may_failover") is not False:
            errors.append("L1 B3 must not grant automatic failover")
        if gh.get("may_merge") is not False:
            errors.append("L1 B3 must not grant automatic merge")

    if gh.get("enabled") and continuous.get("target_effective_cadence_minutes", 60) < 60:
        if not budget.get("ci", {}).get("allow_high_frequency_scheduled_watchdogs"):
            errors.append("high-frequency GitHub Actions supervision is not budget-authorized")
    if gh.get("may_failover") or gh.get("may_merge"):
        warnings.append("GitHub Actions supervisor has mutation authority; verify L3+, least privilege and drills")

    workflow = Path(ROOT) / ".github" / "workflows" / "onecompany-handoff-supervision.yml"
    if gh.get("enabled") and not workflow.exists():
        errors.append("active GitHub Actions supervision requires onecompany-handoff-supervision.yml")

    chatgpt = supervision.get("chatgpt_tasks", {})
    offsets = chatgpt.get("offset_minutes", [])
    if not isinstance(offsets, list) or not offsets:
        errors.append("supervision.chatgpt_tasks.offset_minutes must be a non-empty list")
    elif any(not isinstance(v, int) or v < 0 or v > 59 for v in offsets):
        errors.append("ChatGPT supervisor offsets must be integer minutes 0..59")
    elif len(offsets) != len(set(offsets)):
        errors.append("ChatGPT supervisor offsets must be unique")
    if chatgpt.get("may_mutate") and supervision.get("mode") != "orchestrate":
        errors.append("ChatGPT scheduled tasks may mutate only in orchestrate mode")

    issue = supervision.get("coordination", {}).get("team_room_issue_number")
    if issue is not None and (not isinstance(issue, int) or issue <= 0):
        errors.append("team_room_issue_number must be null or a positive integer")

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
