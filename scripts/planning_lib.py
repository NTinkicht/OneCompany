#!/usr/bin/env python3
"""Deterministic planning, priority, dependency, and parallel-safety helpers."""
from __future__ import annotations

import fnmatch
from typing import Any

DONE = {"MERGED", "DONE"}
ACTIVEISH = {"LEASED", "IN_PROGRESS", "CI_PENDING", "REVIEW_PENDING", "REMEDIATION", "MERGE_READY"}

DEFAULT_PRIORITY_WEIGHTS = {
    "business_value": 1.0,
    "time_criticality": 1.0,
    "risk_reduction": 1.0,
    "dependency_unlock": 1.0,
}


def by_id(work: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in work if isinstance(item.get("id"), str) and item.get("id")}


def dependency_closure(work_map: dict[str, dict[str, Any]], start: str) -> set[str]:
    result: set[str] = set()
    stack = list(work_map.get(start, {}).get("dependencies", []))
    while stack:
        node = str(stack.pop())
        if node in result:
            continue
        result.add(node)
        stack.extend(work_map.get(node, {}).get("dependencies", []))
    return result


def priority_score(item: dict[str, Any], planning: dict[str, Any]) -> float:
    inputs = item.get("priority_inputs")
    if not isinstance(inputs, dict):
        return float(item.get("priority", 0) or 0)
    policy = planning.get("prioritization", {})
    weights = dict(DEFAULT_PRIORITY_WEIGHTS)
    if isinstance(policy.get("weights"), dict):
        for key in weights:
            try:
                weights[key] = float(policy["weights"].get(key, weights[key]))
            except (TypeError, ValueError):
                pass
    numerator = 0.0
    for key, weight in weights.items():
        try:
            numerator += max(0.0, float(inputs.get(key, 0))) * weight
        except (TypeError, ValueError):
            pass
    estimate = item.get("estimate") if isinstance(item.get("estimate"), dict) else {}
    try:
        job_size = max(float(estimate.get("job_size", inputs.get("job_size", 1))), 0.1)
    except (TypeError, ValueError):
        job_size = 1.0
    try:
        confidence = float(estimate.get("confidence", inputs.get("confidence", 1.0)))
    except (TypeError, ValueError):
        confidence = 1.0
    if confidence > 1:
        confidence /= 100.0
    confidence = min(max(confidence, 0.0), 1.0)
    return confidence * numerator / job_size


def _scope_prefix(pattern: str) -> str:
    value = pattern.replace("\\", "/").strip().lstrip("./")
    wildcard_positions = [value.find(ch) for ch in ("*", "?", "[") if value.find(ch) >= 0]
    if wildcard_positions:
        value = value[:min(wildcard_positions)]
    return value.rstrip("/")


def _has_wildcards(pattern: str) -> bool:
    return any(ch in pattern for ch in ("*", "?", "["))


def scopes_overlap(left: str, right: str) -> bool:
    a = left.replace("\\", "/").strip().lstrip("./")
    b = right.replace("\\", "/").strip().lstrip("./")
    if not a or not b:
        return True
    if a in {"*", "**", "**/*"} or b in {"*", "**", "**/*"}:
        return True
    aw, bw = _has_wildcards(a), _has_wildcards(b)
    if not aw and not bw:
        if a == b:
            return True
        return False
    if aw and fnmatch.fnmatchcase(b, a):
        return True
    if bw and fnmatch.fnmatchcase(a, b):
        return True
    ap, bp = _scope_prefix(a), _scope_prefix(b)
    if not ap or not bp:
        return True
    return ap == bp or ap.startswith(bp + "/") or bp.startswith(ap + "/")


def locks_overlap(left: str, right: str) -> bool:
    a, b = left.strip(), right.strip()
    if not a or not b:
        return False
    if a == "*" or b == "*":
        return True
    if a == b:
        return True
    if a.endswith(":*") and b.startswith(a[:-1]):
        return True
    if b.endswith(":*") and a.startswith(b[:-1]):
        return True
    return False


def work_units_conflict(
    left: dict[str, Any],
    right: dict[str, Any],
    planning: dict[str, Any],
    work_map: dict[str, dict[str, Any]] | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    left_id, right_id = str(left.get("id", "")), str(right.get("id", ""))
    if left_id and left_id == right_id:
        return True, ["same_work_unit"]
    parallel = planning.get("parallel_execution", {})
    if not parallel.get("enabled", False):
        return True, ["parallel_execution_disabled"]
    if left.get("parallelism") == "serial" or right.get("parallelism") == "serial":
        reasons.append("serial_policy")
    if left.get("risk_class") == "CRITICAL" or right.get("risk_class") == "CRITICAL":
        if parallel.get("critical_risk_default") == "serialize":
            reasons.append("critical_risk_serialized")
    if work_map and left_id and right_id:
        if right_id in dependency_closure(work_map, left_id) or left_id in dependency_closure(work_map, right_id):
            reasons.append("dependency_relationship")
    left_locks = [str(v) for v in left.get("resource_locks", [])]
    right_locks = [str(v) for v in right.get("resource_locks", [])]
    if any(locks_overlap(a, b) for a in left_locks for b in right_locks):
        reasons.append("resource_lock_overlap")
    left_scope = [str(v) for v in left.get("write_scope", [])]
    right_scope = [str(v) for v in right.get("write_scope", [])]
    require_scope = parallel.get("require_write_scope_for_parallel", True)
    if require_scope and (not left_scope or not right_scope):
        reasons.append("unknown_write_scope")
    elif any(scopes_overlap(a, b) for a in left_scope for b in right_scope):
        reasons.append("write_scope_overlap")
    return bool(reasons), sorted(set(reasons))


def dependency_ready(item: dict[str, Any], work_map: dict[str, dict[str, Any]], durable_done: set[str] | None = None) -> tuple[bool, list[str], list[str]]:
    durable_done = durable_done or set()
    missing: list[str] = []
    unsatisfied: list[str] = []
    for dep in item.get("dependencies", []):
        dep = str(dep)
        if dep in durable_done:
            continue
        if dep not in work_map:
            missing.append(dep)
        elif work_map[dep].get("status") not in DONE:
            unsatisfied.append(dep)
    return not missing and not unsatisfied, missing, unsatisfied


def active_work_items(active_leases: list[dict[str, Any]], work_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for lease in active_leases:
        wu = lease.get("work_unit")
        if isinstance(wu, str) and wu in work_map:
            items.append(work_map[wu])
        elif isinstance(wu, str):
            items.append({"id": wu, "parallelism": "serial", "write_scope": [], "resource_locks": ["*"], "risk_class": "CRITICAL"})
    return items


def select_parallel_set(
    work: list[dict[str, Any]],
    planning: dict[str, Any],
    active_leases: list[dict[str, Any]] | None = None,
    durable_done: set[str] | None = None,
    include_proposed: bool = False,
) -> dict[str, Any]:
    active_leases = active_leases or []
    durable_done = durable_done or set()
    work_map = by_id(work)
    active_items = active_work_items(active_leases, work_map)
    parallel = planning.get("parallel_execution", {})
    limit = int(parallel.get("max_concurrent_implementation_streams", 1) or 1)
    available = max(limit - len(active_items), 0)
    statuses = {"READY"} | ({"PROPOSED"} if include_proposed else set())
    ranked = sorted(
        [item for item in work if item.get("status") in statuses and item.get("id") not in durable_done],
        key=lambda item: (-priority_score(item, planning), -int(item.get("priority", 0) or 0), str(item.get("id", ""))),
    )
    selected: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in ranked:
        ready, missing, unsatisfied = dependency_ready(item, work_map, durable_done)
        if not ready:
            blocked.append({"id": item.get("id"), "reasons": ["dependency_not_ready"], "missing": missing, "unsatisfied": unsatisfied})
            continue
        conflicts: list[str] = []
        for other in [*active_items, *selected]:
            conflict, reasons = work_units_conflict(item, other, planning, work_map)
            if conflict:
                conflicts.extend(f"{other.get('id')}:{reason}" for reason in reasons)
        if conflicts:
            blocked.append({"id": item.get("id"), "reasons": sorted(set(conflicts))})
            continue
        if len(selected) < available:
            selected.append(item)
        else:
            blocked.append({"id": item.get("id"), "reasons": ["wip_limit"]})
    return {
        "limit": limit,
        "active_count": len(active_items),
        "available_slots": available,
        "selected": selected,
        "blocked": blocked,
        "ranked": ranked,
    }


def critical_path(work: list[dict[str, Any]]) -> dict[str, Any]:
    work_map = by_id(work)
    visiting: set[str] = set()
    memo: dict[str, tuple[float, list[str]]] = {}

    def duration(item: dict[str, Any]) -> float:
        estimate = item.get("estimate") if isinstance(item.get("estimate"), dict) else {}
        try:
            return max(float(estimate.get("job_size", 1)), 0.0)
        except (TypeError, ValueError):
            return 1.0

    def solve(node: str) -> tuple[float, list[str]]:
        if node in memo:
            return memo[node]
        if node in visiting:
            raise ValueError(f"dependency cycle involving {node}")
        visiting.add(node)
        item = work_map[node]
        best_len, best_path = 0.0, []
        for dep in item.get("dependencies", []):
            if dep not in work_map:
                continue
            length, path = solve(str(dep))
            if length > best_len:
                best_len, best_path = length, path
        visiting.remove(node)
        result = (best_len + duration(item), [*best_path, node])
        memo[node] = result
        return result

    best = (0.0, [])
    for node in sorted(work_map):
        candidate = solve(node)
        if candidate[0] > best[0]:
            best = candidate
    return {"job_size": best[0], "path": best[1]}
