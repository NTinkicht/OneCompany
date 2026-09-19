#!/usr/bin/env python3
"""Validate deterministic Work Unit dependency, planning, and parallel-conflict semantics."""
from __future__ import annotations

import sys

from onecompany_lib import CONTROL, load_json
from planning_lib import by_id, work_units_conflict
from stream_binding import duplicate_queue_binding_violations

ACTIVEISH = {"LEASED", "IN_PROGRESS", "CI_PENDING", "REVIEW_PENDING", "REMEDIATION", "MERGE_READY"}


def main() -> int:
    queue = load_json(CONTROL / "queue.json"); planning = load_json(CONTROL / "planning.json")
    work = queue.get("work_units", []); errors: list[str] = []; warnings: list[str] = []
    work_map = by_id(work)
    errors.extend(duplicate_queue_binding_violations(work))
    if len(work_map) != len([item for item in work if isinstance(item.get("id"), str) and item.get("id")]):
        seen: set[str] = set()
        for item in work:
            wu_id = item.get("id")
            if not isinstance(wu_id, str) or not wu_id:
                errors.append("work unit missing non-empty id")
            elif wu_id in seen:
                errors.append(f"duplicate work unit id: {wu_id}")
            seen.add(str(wu_id))

    graph: dict[str, list[str]] = {}
    for wu_id, item in work_map.items():
        deps = item.get("dependencies", [])
        if not isinstance(deps, list):
            errors.append(f"{wu_id}: dependencies must be a list"); deps = []
        graph[wu_id] = []
        for dep in deps:
            if dep == wu_id: errors.append(f"{wu_id}: self-dependency is forbidden")
            elif dep not in work_map: errors.append(f"{wu_id}: missing dependency {dep}")
            else: graph[wu_id].append(dep)
        if item.get("status") == "BLOCKED":
            if not item.get("blocked_reason"): warnings.append(f"{wu_id}: BLOCKED should record blocked_reason")
            if not item.get("blocked_owner"): warnings.append(f"{wu_id}: BLOCKED should record blocked_owner")

    visiting: set[str] = set(); visited: set[str] = set(); stack: list[str] = []
    def visit(node: str) -> None:
        if node in visited: return
        if node in visiting:
            start = stack.index(node) if node in stack else 0
            errors.append("dependency cycle: " + " -> ".join(stack[start:] + [node])); return
        visiting.add(node); stack.append(node)
        for dep in graph.get(node, []): visit(dep)
        stack.pop(); visiting.discard(node); visited.add(node)
    for node in sorted(graph): visit(node)

    for item in work:
        if item.get("status") == "READY":
            unsatisfied = [dep for dep in item.get("dependencies", []) if dep in work_map and work_map[dep].get("status") not in {"DONE", "MERGED"}]
            if unsatisfied: warnings.append(f"{item.get('id')}: READY has dependencies not marked DONE/MERGED: {unsatisfied}")
            if planning.get("parallel_execution", {}).get("enabled") and item.get("parallelism", "auto") != "serial" and not item.get("write_scope"):
                warnings.append(f"{item.get('id')}: READY has no write_scope and will be serialized conservatively")

    active_items = [item for item in work if item.get("status") in ACTIVEISH]
    limit = int(planning.get("parallel_execution", {}).get("max_concurrent_implementation_streams", 1) or 1)
    if len(active_items) > limit:
        errors.append(f"queue contains {len(active_items)} active-like WUs above configured WIP limit {limit}")
    for index, left in enumerate(active_items):
        for right in active_items[index + 1:]:
            conflict, reasons = work_units_conflict(left, right, planning, work_map)
            if conflict:
                errors.append(f"active-like WUs {left.get('id')} and {right.get('id')} conflict: {','.join(reasons)}")

    for warning in warnings: print(f"WARN: {warning}")
    if errors:
        for error in errors: print(f"ERROR: {error}")
        print(f"Queue validation FAILED ({len(errors)} error(s), {len(warnings)} warning(s))."); return 1
    print(f"Queue validation PASS ({len(warnings)} warning(s))."); return 0


if __name__ == "__main__":
    sys.exit(main())
