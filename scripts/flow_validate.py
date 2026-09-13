#!/usr/bin/env python3
"""Validate company-wide WIP, actor capacity, and no-idle execution semantics."""
from __future__ import annotations

import sys

from capacity_lib import implementation_capacity_limit, implementation_pool
from onecompany_lib import CONTROL, active_implementation_leases, autonomy_number, load_json
from planning_lib import select_parallel_set


def main() -> int:
    config = load_json(CONTROL / "config.json")
    planning = load_json(CONTROL / "planning.json")
    queue = load_json(CONTROL / "queue.json")
    state = load_json(CONTROL / "state.json")
    actors = load_json(CONTROL / "actors.json")
    readiness = load_json(CONTROL / "readiness.json")
    budget = load_json(CONTROL / "budget.json")
    dispatch = load_json(CONTROL / "dispatch.json")
    errors: list[str] = []
    warnings: list[str] = []
    active = active_implementation_leases(state)
    ready_by_actor = {item.get("actor_id"): item for item in readiness.get("actors", []) if item.get("actor_id")}

    try:
        global_limit = max(int(planning.get("parallel_execution", {}).get("max_concurrent_implementation_streams", 1)), 1)
    except (TypeError, ValueError):
        global_limit = 1
    if len(active) > global_limit:
        errors.append(f"active implementation streams {len(active)} exceed global WIP limit {global_limit}")

    counts: dict[str, int] = {}
    for lease in active:
        actor_id = str(lease.get("actor") or "")
        counts[actor_id] = counts.get(actor_id, 0) + 1
    for actor_id, count in counts.items():
        limit = implementation_capacity_limit(ready_by_actor.get(actor_id))
        if count > limit:
            errors.append(f"actor {actor_id} has {count} implementation streams above verified capacity {limit}")

    plan = select_parallel_set(queue.get("work_units", []), planning, active)
    plan_safe = [item.get("id") for item in plan.get("selected", [])]
    interactive = implementation_pool(actors, readiness, budget, active)
    unattended = implementation_pool(
        actors,
        readiness,
        budget,
        active,
        dispatch_doc=dispatch,
        require_unattended=True,
    )

    try:
        level = autonomy_number(config.get("autonomy", {}).get("level", "L0"))
    except ValueError:
        level = 0
    no_idle = config.get("no_idle", {}).get("enabled") is True
    continuation = config.get("autonomy", {}).get("continue_when_ready_work_exists") is True

    # L4/L5 no-idle applies only to work the company can actually start without
    # human interaction. Interactive capacity remains useful but does not create
    # a false autonomous-idle fault.
    dispatchable = plan_safe[: int(unattended.get("free_slots", 0))]
    if no_idle and level >= 4 and continuation and dispatchable:
        active_wus = {lease.get("work_unit") for lease in active}
        unowned = [wu for wu in dispatchable if wu not in active_wus]
        if unowned:
            errors.append(f"FAULT_IDLE_WITH_READY_WORK: unattended-dispatch-ready work has no implementation lease: {unowned}")
    elif no_idle and level >= 4 and continuation and plan_safe and int(unattended.get("free_slots", 0)) <= 0:
        warnings.append(
            f"CAPACITY_BLOCKED: planning-safe work exists but no unattended implementation route has verified capacity: {plan_safe}"
        )

    cached_safe = state.get("safe_start_candidates", [])
    if cached_safe and sorted(cached_safe) != sorted(dispatchable):
        warnings.append("state.safe_start_candidates differs from deterministic unattended-dispatchable calculation; reconcile cache")

    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Flow validation FAILED ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1

    print(
        f"Flow validation PASS ({len(warnings)} warning(s); "
        f"interactive_slots={interactive.get('free_slots', 0)}; "
        f"unattended_slots={unattended.get('free_slots', 0)}; "
        f"interactive={[row.get('actor') for row in interactive.get('actors', [])]}; "
        f"unattended={[row.get('actor') for row in unattended.get('actors', [])]})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
