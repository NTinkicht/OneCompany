#!/usr/bin/env python3
"""Deterministically exercise distributed lease/gate race semantics without GitHub."""
from __future__ import annotations

import sys

from ledger_lib import derive


def event(index: int, event_type: str, actor: str, payload: dict) -> dict:
    return {
        "version": 1,
        "event_id": f"e{index}",
        "type": event_type,
        "actor": actor,
        "payload": payload,
        "github_created_at": f"2026-01-01T00:00:{index:02d}Z",
        "github_comment_id": index,
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    try:
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU1", "branch": "wu1", "pr": 10, "start_head": "aaa"}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {"lease_id": "L2", "role": "implementation", "work_unit": "WU1", "branch": "wu1-alt", "pr": 11, "start_head": "bbb"}),
        ]
        first = derive(events)
        active = first.get("active_leases", [])
        require(len(active) == 1 and active[0].get("id") == "L1", "first valid implementation lease must win a concurrent claim race")
        require(any(item.get("rejected_lease_id") == "L2" for item in first.get("conflicts", [])), "losing lease must be durably classified as conflict")

        events.append(event(3, "ROLE_LEASE_TRANSFERRED", "claude", {"old_lease_id": "L1", "new_lease_id": "L3", "lease_id": "L3", "role": "implementation", "work_unit": "WU1", "branch": "wu1", "pr": 10, "start_head": "ccc", "parent_lease_id": "L1"}))
        transferred = derive(events, 10)
        active = transferred.get("active_leases", [])
        require(len(active) == 1 and active[0].get("id") == "L3" and active[0].get("actor") == "claude", "atomic failover must leave exactly one replacement writer")
        require(set(transferred.get("material_authors", [])) == {"codex", "claude"}, "failover must preserve cumulative material authorship")

        events.append(event(4, "GATE", "chatgpt", {"pr": 10, "sha": "ddd", "verdict": "PASS — MERGE_READY", "material_authors": ["codex", "claude"], "evidence": ["ci:green"]}))
        gated = derive(events, 10)
        require(gated.get("current_gate", {}).get("sha") == "ddd", "latest trusted gate must bind exact SHA")
        require(gated.get("current_gate", {}).get("reviewer_actor") == "chatgpt", "gate reviewer must remain explicit")

        events.append(event(5, "ROLE_LEASE_RELEASED", "claude", {"lease_id": "L3", "pr": 10, "reason": "merged"}))
        released = derive(events, 10)
        require(released.get("active_leases") == [], "lease release must leave zero active writers")
        print("Ledger race simulation PASS")
        return 0
    except AssertionError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
