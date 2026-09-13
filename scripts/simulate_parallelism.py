#!/usr/bin/env python3
"""Simulate OneCompany conflict-safe parallel planning invariants."""
from __future__ import annotations

import sys

from planning_lib import by_id, select_parallel_set, work_units_conflict


def main() -> int:
    planning = {
        "parallel_execution": {
            "enabled": True, "max_concurrent_implementation_streams": 3,
            "require_write_scope_for_parallel": True, "unknown_scope_behavior": "serialize",
            "critical_risk_default": "serialize", "resource_locking": True, "conflict_policy": "fail_closed",
        },
        "prioritization": {"weights": {"business_value": 1, "time_criticality": 1, "risk_reduction": 1, "dependency_unlock": 1}},
    }
    work = [
        {"id": "WU-A", "title": "A", "status": "READY", "priority": 10, "dependencies": [], "risk_class": "LOW", "write_scope": ["src/a/**"], "resource_locks": [], "parallelism": "auto"},
        {"id": "WU-B", "title": "B", "status": "READY", "priority": 9, "dependencies": [], "risk_class": "LOW", "write_scope": ["src/b/**"], "resource_locks": [], "parallelism": "auto"},
        {"id": "WU-C", "title": "C", "status": "READY", "priority": 8, "dependencies": [], "risk_class": "LOW", "write_scope": ["src/a/file.py"], "resource_locks": [], "parallelism": "auto"},
        {"id": "WU-D", "title": "D", "status": "READY", "priority": 7, "dependencies": [], "risk_class": "LOW", "write_scope": ["docs/**"], "resource_locks": ["db:schema"], "parallelism": "auto"},
        {"id": "WU-E", "title": "E", "status": "READY", "priority": 6, "dependencies": [], "risk_class": "LOW", "write_scope": ["tests/**"], "resource_locks": ["db:*"], "parallelism": "auto"},
    ]
    tests: list[tuple[str, bool]] = []
    wm = by_id(work)
    conflict_ab, _ = work_units_conflict(work[0], work[1], planning, wm)
    tests.append(("disjoint write scopes may parallelize", not conflict_ab))
    conflict_ac, _ = work_units_conflict(work[0], work[2], planning, wm)
    tests.append(("overlapping write scopes conflict", conflict_ac))
    conflict_de, _ = work_units_conflict(work[3], work[4], planning, wm)
    tests.append(("resource lock namespaces conflict", conflict_de))
    selected = select_parallel_set(work, planning)
    ids = {item["id"] for item in selected["selected"]}
    tests.append(("planner selects disjoint high-priority work", {"WU-A", "WU-B"}.issubset(ids)))
    tests.append(("planner excludes overlapping WU-C", "WU-C" not in ids))
    unknown = {"id": "WU-X", "status": "READY", "priority": 1, "dependencies": [], "risk_class": "LOW", "write_scope": [], "resource_locks": [], "parallelism": "auto"}
    conflict_unknown, reasons = work_units_conflict(work[0], unknown, planning, {**wm, "WU-X": unknown})
    tests.append(("unknown scope fails closed", conflict_unknown and "unknown_write_scope" in reasons))
    critical = {"id": "WU-Z", "status": "READY", "priority": 1, "dependencies": [], "risk_class": "CRITICAL", "write_scope": ["unrelated/**"], "resource_locks": [], "parallelism": "auto"}
    conflict_critical, reasons = work_units_conflict(work[1], critical, planning, {**wm, "WU-Z": critical})
    tests.append(("critical risk defaults to serialization", conflict_critical and "critical_risk_serialized" in reasons))

    failures = 0
    for label, passed in tests:
        print(("PASS" if passed else "FAIL") + ": " + label)
        failures += 0 if passed else 1
    print(f"\nParallelism simulation: {len(tests)-failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
