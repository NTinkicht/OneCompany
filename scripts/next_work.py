#!/usr/bin/env python3
"""Select dependency-ready Work Units without mutating the queue."""
from __future__ import annotations

import argparse
import json
import sys

from ledger_lib import derive, ledger_enabled, list_events
from onecompany_lib import CONTROL, active_implementation_leases, emergency_stop_active, load_json

DONE = {"MERGED", "DONE"}
CANDIDATE = {"PROPOSED", "READY"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Show all dependency-ready candidates even when a canonical stream is active")
    args = parser.parse_args()
    if emergency_stop_active():
        print(json.dumps({"status": "EMERGENCY_STOP_ACTIVE", "candidates": []}, indent=2))
        return 0

    queue = load_json(CONTROL / "queue.json")
    state = load_json(CONTROL / "state.json")
    work = queue.get("work_units", [])
    by_id = {item.get("id"): item for item in work}

    active = active_implementation_leases(state)
    if ledger_enabled():
        try:
            active = [item for item in derive(list_events()).get("active_leases", []) if item.get("role") == "implementation"]
        except Exception as exc:
            print(json.dumps({"status": "BLOCKED_LEDGER_UNAVAILABLE", "candidates": [], "error": str(exc)}, indent=2))
            return 2

    if not args.all and (active or state.get("current_pr") is not None):
        print(json.dumps({"status": "CANONICAL_STREAM_ACTIVE", "candidates": []}, indent=2))
        return 0

    candidates: list[dict] = []
    blocked: list[dict] = []
    for item in work:
        if item.get("status") not in CANDIDATE:
            continue
        deps = item.get("dependencies", [])
        missing = [dep for dep in deps if dep not in by_id]
        unsatisfied = [dep for dep in deps if dep in by_id and by_id[dep].get("status") not in DONE]
        if missing or unsatisfied:
            blocked.append({"id": item.get("id"), "missing": missing, "unsatisfied": unsatisfied})
            continue
        candidates.append(item)

    candidates.sort(key=lambda item: (-int(item.get("priority", 0)), str(item.get("id", ""))))
    print(json.dumps({"status": "READY" if candidates else "NO_READY_WORK", "candidates": candidates, "blocked": blocked}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
