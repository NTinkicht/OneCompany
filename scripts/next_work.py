#!/usr/bin/env python3
"""Select dependency-ready Work Units using conflict-aware parallel planning."""
from __future__ import annotations

import argparse
import json
import sys

from ledger_lib import derive, ledger_enabled, list_events
from onecompany_lib import CONTROL, active_implementation_leases, emergency_stop_active, load_json
from planning_lib import priority_score, select_parallel_set


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Show the complete ranked READY set, not only safe start candidates")
    parser.add_argument("--include-proposed", action="store_true", help="Planning-only view; continuous execution must not start PROPOSED work")
    args = parser.parse_args()
    if emergency_stop_active():
        print(json.dumps({"status": "EMERGENCY_STOP_ACTIVE", "candidates": []}, indent=2))
        return 0

    queue = load_json(CONTROL / "queue.json")
    planning = load_json(CONTROL / "planning.json")
    state = load_json(CONTROL / "state.json")
    work = queue.get("work_units", [])
    active = active_implementation_leases(state)
    durable_done: set[str] = set()
    if ledger_enabled():
        try:
            view = derive(list_events())
            active = [item for item in view.get("active_leases", []) if item.get("role") == "implementation"]
            durable_done = set(view.get("merged_work_units", []))
        except Exception as exc:
            print(json.dumps({"status": "BLOCKED_LEDGER_UNAVAILABLE", "candidates": [], "error": str(exc)}, indent=2))
            return 2

    result = select_parallel_set(work, planning, active, durable_done, args.include_proposed)
    selected = result["ranked"] if args.all else result["selected"]
    status = "READY"
    if not selected:
        if result["available_slots"] <= 0:
            status = "WIP_LIMIT_REACHED"
        elif result["blocked"]:
            status = "NO_CONFLICT_FREE_READY_WORK"
        else:
            status = "NO_READY_WORK"
    payload = {
        "status": status,
        "max_concurrent_implementation_streams": result["limit"],
        "active_implementation_streams": result["active_count"],
        "available_slots": result["available_slots"],
        "candidates": [
            {
                **item,
                "computed_priority_score": round(priority_score(item, planning), 4),
            }
            for item in selected
        ],
        "blocked": result["blocked"],
        "durably_merged": sorted(durable_done),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
