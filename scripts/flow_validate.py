#!/usr/bin/env python3
"""Validate company-wide WIP, actor capacity, and no-idle execution semantics."""
from __future__ import annotations

import sys

from onecompany_lib import CONTROL, active_implementation_leases, autonomy_number, budget_allows, load_json
from planning_lib import select_parallel_set


def implementation_capacity_slots(actor: dict, ready: dict | None, budget: dict, active: list[dict]) -> tuple[int, list[str]]:
    """Return currently free verified implementation slots for one actor."""
    reasons: list[str] = []
    actor_id = actor.get("id")
    if not actor.get("enabled"): reasons.append("disabled")
    if not actor.get("configured"): reasons.append("not_configured")
    if "implementation" not in actor.get("capabilities", []): reasons.append("implementation_not_declared")
    if not budget_allows(actor.get("cost_class", "UNKNOWN_COST"), budget): reasons.append("budget")
    if ready is None:
        reasons.append("missing_readiness")
        return 0, reasons
    if ready.get("setup_state") not in {"ready", "degraded"}: reasons.append("not_ready")
    if "implementation" not in ready.get("verified_capabilities", []): reasons.append("implementation_not_verified")
    if "implementation" in ready.get("temporarily_unavailable_capabilities", []): reasons.append("temporarily_unavailable")
    access = ready.get("repository_access", {})
    if not access.get("read") or not access.get("write"): reasons.append("repository_write_path_not_verified")
    try: capacity = max(int(ready.get("capacity", {}).get("implementation_streams", 1)), 1)
    except (TypeError, ValueError): capacity = 1
    current = sum(1 for lease in active if lease.get("actor") == actor_id and lease.get("role") == "implementation")
    free = max(capacity - current, 0)
    if free <= 0: reasons.append("actor_capacity")
    return (free if not [r for r in reasons if r != "actor_capacity"] else 0), reasons


def implementation_ready_actor(actor: dict, ready: dict | None, budget: dict, active: list[dict]) -> tuple[bool, list[str]]:
    slots, reasons = implementation_capacity_slots(actor, ready, budget, active)
    return slots > 0, reasons


def main() -> int:
    config = load_json(CONTROL / "config.json"); planning = load_json(CONTROL / "planning.json")
    queue = load_json(CONTROL / "queue.json"); state = load_json(CONTROL / "state.json")
    actors = load_json(CONTROL / "actors.json"); readiness = load_json(CONTROL / "readiness.json"); budget = load_json(CONTROL / "budget.json")
    errors: list[str] = []; warnings: list[str] = []
    active = active_implementation_leases(state)
    ready_by_actor = {item.get("actor_id"): item for item in readiness.get("actors", []) if item.get("actor_id")}

    try: global_limit = max(int(planning.get("parallel_execution", {}).get("max_concurrent_implementation_streams", 1)), 1)
    except (TypeError, ValueError): global_limit = 1
    if len(active) > global_limit: errors.append(f"active implementation streams {len(active)} exceed global WIP limit {global_limit}")
    counts: dict[str, int] = {}
    for lease in active:
        actor_id = str(lease.get("actor") or "")
        counts[actor_id] = counts.get(actor_id, 0) + 1
    for actor_id, count in counts.items():
        ready = ready_by_actor.get(actor_id)
        try: limit = max(int((ready or {}).get("capacity", {}).get("implementation_streams", 1)), 1)
        except (TypeError, ValueError): limit = 1
        if count > limit: errors.append(f"actor {actor_id} has {count} implementation streams above verified capacity {limit}")

    plan = select_parallel_set(queue.get("work_units", []), planning, active)
    plan_safe = [item.get("id") for item in plan.get("selected", [])]
    free_worker_slots = 0; eligible: list[str] = []
    for actor in actors.get("actors", []):
        slots, _ = implementation_capacity_slots(actor, ready_by_actor.get(actor.get("id")), budget, active)
        if slots > 0:
            eligible.append(str(actor.get("id")))
            free_worker_slots += slots

    try: level = autonomy_number(config.get("autonomy", {}).get("level", "L0"))
    except ValueError: level = 0
    no_idle = config.get("no_idle", {}).get("enabled") is True
    continuation = config.get("autonomy", {}).get("continue_when_ready_work_exists") is True
    dispatchable = plan_safe[:free_worker_slots]
    if no_idle and level >= 4 and continuation and dispatchable:
        active_wus = {lease.get("work_unit") for lease in active}
        unowned = [wu for wu in dispatchable if wu not in active_wus]
        if unowned: errors.append(f"FAULT_IDLE_WITH_READY_WORK: dispatch-ready work has no implementation lease: {unowned}")
    elif no_idle and level >= 4 and continuation and plan_safe and free_worker_slots <= 0:
        warnings.append(f"CAPACITY_BLOCKED: planning-safe work exists but no implementation-ready actor has capacity: {plan_safe}")

    cached_safe = state.get("safe_start_candidates", [])
    if cached_safe and sorted(cached_safe) != sorted(dispatchable): warnings.append("state.safe_start_candidates differs from deterministic dispatchable planning calculation; reconcile cache")

    for warning in warnings: print(f"WARN: {warning}")
    if errors:
        for error in errors: print(f"ERROR: {error}")
        print(f"Flow validation FAILED ({len(errors)} error(s), {len(warnings)} warning(s))."); return 1
    print(f"Flow validation PASS ({len(warnings)} warning(s); free_worker_slots={free_worker_slots}; eligible={eligible})."); return 0


if __name__ == "__main__":
    sys.exit(main())
