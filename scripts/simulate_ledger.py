#!/usr/bin/env python3
"""Deterministically exercise distributed lease/gate race semantics without GitHub."""
from __future__ import annotations

import sys

from ledger_lib import derive


def event(index: int, event_type: str, actor: str, payload: dict, event_id: str | None = None) -> dict:
    return {"version": 1, "event_id": event_id or f"e{index}", "type": event_type, "actor": actor, "payload": payload, "github_created_at": f"2026-01-01T00:00:{index:02d}Z", "github_comment_id": index}

def require(condition: bool, message: str) -> None:
    if not condition: raise AssertionError(message)

def main() -> int:
    try:
        events = [
            event(1, "ROLE_LEASE_ASSIGNED", "codex", {"lease_id": "L1", "role": "implementation", "work_unit": "WU1", "branch": "wu1", "pr": 10, "start_head": "aaa"}),
            event(2, "ROLE_LEASE_ASSIGNED", "chatgpt", {"lease_id": "L2", "role": "implementation", "work_unit": "WU1", "branch": "wu1-alt", "pr": 11, "start_head": "bbb"}),
        ]
        first = derive(events); active = first.get("active_leases", [])
        require(len(active) == 1 and active[0].get("id") == "L1", "first valid implementation lease must win concurrent claim")
        require(any(item.get("rejected_lease_id") == "L2" for item in first.get("conflicts", [])), "losing lease must be classified")
        events.append(event(3, "ROLE_LEASE_TRANSFERRED", "claude", {"old_lease_id": "L1", "new_lease_id": "L3", "lease_id": "L3", "role": "implementation", "work_unit": "WU1", "branch": "wu1", "pr": 10, "start_head": "ccc", "parent_lease_id": "L1"}))
        transferred = derive(events, 10); active = transferred.get("active_leases", [])
        require(len(active) == 1 and active[0].get("id") == "L3" and active[0].get("actor") == "claude", "failover must leave exactly one writer")
        require(set(transferred.get("material_authors", [])) == {"codex", "claude"}, "failover must preserve authorship")
        events.append(event(4, "GATE", "chatgpt", {"pr": 10, "sha": "ddd", "verdict": "PASS — MERGE_READY", "material_authors": ["codex", "claude"], "evidence": ["ci:green"]}))
        gated = derive(events, 10); require(gated.get("current_gate", {}).get("stale") is False, "matching non-author gate should be current")
        events.append(event(5, "MATERIAL_AUTHOR", "chatgpt", {"pr": 10}))
        stale = derive(events, 10); require(stale.get("current_gate", {}).get("stale") is True, "gate must stale when reviewer later becomes material author")
        require("reviewer_is_now_material_author" in stale.get("current_gate", {}).get("stale_reasons", []), "stale reason should expose reviewer conflict")
        events.append(event(6, "ROLE_LEASE_RELEASED", "claude", {"lease_id": "L3", "pr": 10, "reason": "merged"}))
        events.append(event(7, "MERGED", "human-owner", {"pr": 10, "work_unit": "WU1", "approved_head": "ddd", "merge_sha": "mmm"}))
        released = derive(events); require(released.get("active_leases") == [], "release must leave zero active writers"); require("WU1" in released.get("merged_work_units", []), "merge must durably unlock dependent work")
        events.append(event(8, "SUPERVISION_CHECK", "chatgpt", {"state": "noop"}, event_id="e7"))
        replay = derive(events); require(any(item.get("reason") == "duplicate_event_id_ignored" for item in replay.get("conflicts", [])), "duplicate event IDs must be ignored deterministically")
        print("Ledger race simulation PASS"); return 0
    except AssertionError as exc:
        print(f"ERROR: {exc}"); return 1


if __name__ == "__main__": sys.exit(main())
