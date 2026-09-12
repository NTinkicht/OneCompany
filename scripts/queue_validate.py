#!/usr/bin/env python3
"""Validate deterministic Work Unit dependency-graph semantics."""
from __future__ import annotations

import sys

from onecompany_lib import CONTROL, load_json

ACTIVEISH = {"LEASED", "IN_PROGRESS", "CI_PENDING", "REVIEW_PENDING", "REMEDIATION", "MERGE_READY"}


def main() -> int:
    queue = load_json(CONTROL / "queue.json")
    work = queue.get("work_units", [])
    errors: list[str] = []
    warnings: list[str] = []
    by_id: dict[str, dict] = {}
    for item in work:
        wu_id = item.get("id")
        if not isinstance(wu_id, str) or not wu_id:
            errors.append("work unit missing non-empty id"); continue
        if wu_id in by_id: errors.append(f"duplicate work unit id: {wu_id}")
        by_id[wu_id] = item

    graph: dict[str, list[str]] = {}
    for wu_id, item in by_id.items():
        deps = item.get("dependencies", [])
        if not isinstance(deps, list):
            errors.append(f"{wu_id}: dependencies must be a list"); deps = []
        graph[wu_id] = []
        for dep in deps:
            if dep == wu_id: errors.append(f"{wu_id}: self-dependency is forbidden")
            elif dep not in by_id: errors.append(f"{wu_id}: missing dependency {dep}")
            else: graph[wu_id].append(dep)

    visiting: set[str] = set(); visited: set[str] = set(); stack: list[str] = []
    def visit(node: str) -> None:
        if node in visited: return
        if node in visiting:
            try: start = stack.index(node); cycle = stack[start:] + [node]
            except ValueError: cycle = [node, node]
            errors.append("dependency cycle: " + " -> ".join(cycle)); return
        visiting.add(node); stack.append(node)
        for dep in graph.get(node, []): visit(dep)
        stack.pop(); visiting.discard(node); visited.add(node)
    for node in sorted(graph): visit(node)

    activeish = [item.get("id") for item in work if item.get("status") in ACTIVEISH]
    if len(activeish) > 1:
        warnings.append(f"queue contains multiple active-like WUs {activeish}; live ledger/state must reconcile to one canonical stream")
    for item in work:
        if item.get("status") == "READY":
            unsatisfied = [dep for dep in item.get("dependencies", []) if dep in by_id and by_id[dep].get("status") not in {"DONE", "MERGED"}]
            if unsatisfied: warnings.append(f"{item.get('id')}: READY has dependencies not marked DONE/MERGED in queue cache: {unsatisfied}")

    for warning in warnings: print(f"WARN: {warning}")
    if errors:
        for error in errors: print(f"ERROR: {error}")
        print(f"Queue validation FAILED ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1
    print(f"Queue validation PASS ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__": sys.exit(main())
