#!/usr/bin/env python3
"""Deterministically exercise distributed lease/gate and parallel-safety race semantics without GitHub."""
from __future__ import annotations

import sys

from ledger_lib import derive
from onecompany_lib import CONTROL, load_json
from planning_lib import by_id, work_units_conflict


def event(index: int, event_type: str, actor: str, payload: dict, event_id: str | None = None) -> dict:
    return {
        "version": 1,
        "event_id": event_id or f"e{index}",
        "type": event_type,
        "actor": actor,
        "payload": payload,
        "github_created_at": f"2026-01-01T00:00:{index:02d}Z",
        "github_comment_id": index,
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def snap(
    scope: str,
    lock: str | None = None,
    dependencies: list[str] | None = None,
    dependency_closure: list[str] | None = None,
) -> dict:
    dependencies = dependencies or []
    return {
        "write_scope": [scope],
        "resource_locks": [lock] if lock else [],
        "parallelism": "auto",
        "risk_class": "LOW",
        "dependencies": dependencies,
        "dependency_closure": dependency_closure if dependency_closure is not None else list(dependencies),
    }


def main() -> int:
    try:
        events = [
            event(
                1,
                "ROLE_LEASE_ASSIGNED",
                "codex",
                {
                    "lease_id": "L1",
                    "role": "implementation",
                    "work_unit": "WU1",
                    "branch": "wu1",
                    "pr": 10,
                    "start_head": "aaa",
                    "planning_snapshot": snap("src/a/**"),
                },
            ),
            event(
                2,
                "ROLE_LEASE_ASSIGNED",
                "chatgpt",
                {
                    "lease_id": "L2",
                    "role": "implementation",
                    "work_unit": "WU1",
                    "branch": "wu1-alt",
                    "pr": 11,
                    "start_head": "bbb",
                    "planning_snapshot": snap("src/a/**"),
                },
            ),
        ]
        first = derive(events)
        active = first.get("active_leases", [])
        require(
            len(active) == 1 and active[0].get("id") == "L1",
            "first valid implementation lease must win same-WU concurrent claim",
        )
        require(
            any(item.get("rejected_lease_id") == "L2" for item in first.get("rejected_claims", [])),
            "losing same-WU lease must be retained as an informational rejected claim",
        )
        require(
            first.get("integrity_conflicts") == [],
            "an expected lost lease race must not create an integrity blocker",
        )

        events.append(
            event(
                3,
                "ROLE_LEASE_TRANSFERRED",
                "claude",
                {
                    "old_lease_id": "L1",
                    "new_lease_id": "L3",
                    "lease_id": "L3",
                    "role": "implementation",
                    "work_unit": "WU1",
                    "branch": "wu1",
                    "pr": 10,
                    "start_head": "ccc",
                    "parent_lease_id": "L1",
                    "planning_snapshot": snap("src/a/**"),
                },
            )
        )
        transferred = derive(events, 10)
        active = transferred.get("active_leases", [])
        require(
            len(active) == 1 and active[0].get("id") == "L3" and active[0].get("actor") == "claude",
            "failover must leave exactly one writer for WU1",
        )
        require(
            set(transferred.get("material_authors", [])) == {"codex", "claude"},
            "failover must preserve authorship",
        )

        events.append(
            event(
                4,
                "ROLE_LEASE_ASSIGNED",
                "codex",
                {
                    "lease_id": "L4",
                    "role": "implementation",
                    "work_unit": "WU2",
                    "branch": "wu2",
                    "pr": 12,
                    "start_head": "eee",
                    "planning_snapshot": snap("src/b/**"),
                },
            )
        )
        parallel = derive(events)
        require(
            {item.get("id") for item in parallel.get("active_leases", [])} == {"L3", "L4"},
            "disjoint WUs must be able to hold concurrent leases",
        )

        events.append(
            event(
                5,
                "ROLE_LEASE_ASSIGNED",
                "chatgpt",
                {
                    "lease_id": "L5",
                    "role": "implementation",
                    "work_unit": "WU3",
                    "branch": "wu3",
                    "pr": 13,
                    "start_head": "fff",
                    "planning_snapshot": snap("src/a/file.py"),
                },
            )
        )
        overlap = derive(events)
        require(
            "L5" not in {item.get("id") for item in overlap.get("active_leases", [])},
            "overlapping WU must lose lease race",
        )
        require(
            any(item.get("rejected_lease_id") == "L5" for item in overlap.get("rejected_claims", [])),
            "overlap rejection must be explicit and informational",
        )
        require(
            overlap.get("integrity_conflicts") == [],
            "ordinary scheduling rejection must not become an integrity conflict",
        )

        events.append(
            event(
                6,
                "GATE",
                "chatgpt",
                {
                    "pr": 10,
                    "sha": "ddd",
                    "verdict": "PASS — MERGE_READY",
                    "material_authors": ["codex", "claude"],
                    "evidence": ["ci:green"],
                },
            )
        )
        gated = derive(events, 10)
        require(gated.get("current_gate", {}).get("stale") is False, "matching non-author gate should be current")
        events.append(event(7, "MATERIAL_AUTHOR", "chatgpt", {"pr": 10}))
        stale = derive(events, 10)
        require(stale.get("current_gate", {}).get("stale") is True, "gate must stale when reviewer later becomes material author")
        require(
            "reviewer_is_now_material_author" in stale.get("current_gate", {}).get("stale_reasons", []),
            "stale reason should expose reviewer conflict",
        )

        events.append(event(8, "ROLE_LEASE_RELEASED", "claude", {"lease_id": "L3", "pr": 10, "reason": "merged"}))
        events.append(event(9, "MERGED", "human-owner", {"pr": 10, "work_unit": "WU1", "approved_head": "ddd", "merge_sha": "mmm"}))
        after_wu1 = derive(events)
        require(
            {item.get("id") for item in after_wu1.get("active_leases", [])} == {"L4"},
            "merging WU1 must not release independent WU2",
        )
        require("WU1" in after_wu1.get("merged_work_units", []), "merge must durably unlock dependent work")
        events.append(event(10, "ROLE_LEASE_RELEASED", "codex", {"lease_id": "L4", "pr": 12, "reason": "merged"}))
        released = derive(events)
        require(released.get("active_leases") == [], "releasing all streams must leave zero active writers")

        # Historical rejected claims must not poison future leasing.
        events.append(
            event(
                11,
                "ROLE_LEASE_ASSIGNED",
                "gemini-cli",
                {
                    "lease_id": "L6",
                    "role": "implementation",
                    "work_unit": "WU4",
                    "branch": "wu4",
                    "pr": 14,
                    "start_head": "ggg",
                    "planning_snapshot": snap("src/d/**"),
                },
            )
        )
        liveness = derive(events)
        require(
            "L6" in {item.get("id") for item in liveness.get("active_leases", [])},
            "future legal work must remain leasable after historical rejected claims",
        )
        require(liveness.get("integrity_conflicts") == [], "historical rejected claims must not block progression")

        # Local and durable admission must agree on transitive dependency relationships.
        planning = load_json(CONTROL / "planning.json")
        work = [
            {"id": "WU-A", "dependencies": ["WU-B"], "write_scope": ["src/a/**"], "resource_locks": [], "parallelism": "auto", "risk_class": "LOW"},
            {"id": "WU-B", "dependencies": ["WU-C"], "write_scope": ["src/b/**"], "resource_locks": [], "parallelism": "auto", "risk_class": "LOW"},
            {"id": "WU-C", "dependencies": [], "write_scope": ["src/c/**"], "resource_locks": [], "parallelism": "auto", "risk_class": "LOW"},
        ]
        work_map = by_id(work)
        local_conflict, local_reasons = work_units_conflict(work_map["WU-A"], work_map["WU-C"], planning, work_map)
        require(local_conflict and "dependency_relationship" in local_reasons, "local admission must see transitive A→B→C dependency")

        durable_events = [
            event(
                20,
                "ROLE_LEASE_ASSIGNED",
                "codex",
                {
                    "lease_id": "LC",
                    "role": "implementation",
                    "work_unit": "WU-C",
                    "branch": "wu-c",
                    "pr": 20,
                    "start_head": "ccc",
                    "planning_snapshot": snap("src/c/**"),
                },
            ),
            event(
                21,
                "ROLE_LEASE_ASSIGNED",
                "claude",
                {
                    "lease_id": "LA",
                    "role": "implementation",
                    "work_unit": "WU-A",
                    "branch": "wu-a",
                    "pr": 21,
                    "start_head": "aaa",
                    "planning_snapshot": snap(
                        "src/a/**",
                        dependencies=["WU-B"],
                        dependency_closure=["WU-B", "WU-C"],
                    ),
                },
            ),
        ]
        durable = derive(durable_events)
        require(
            "LA" not in {item.get("id") for item in durable.get("active_leases", [])},
            "durable admission must reject a transitive dependency that local admission rejects",
        )
        durable_rejection = next(
            (item for item in durable.get("rejected_claims", []) if item.get("rejected_lease_id") == "LA"),
            None,
        )
        require(durable_rejection is not None, "durable transitive dependency rejection must be recorded")
        require(
            any("dependency_relationship" in violation.get("details", []) for violation in durable_rejection.get("violations", [])),
            "durable rejection must expose the same dependency relationship reason",
        )

        # True integrity faults remain blocking until an explicit append-only resolution event.
        events.append(event(12, "SUPERVISION_CHECK", "chatgpt", {"state": "noop"}, event_id="e9"))
        replay = derive(events)
        duplicate = next(
            (item for item in replay.get("integrity_conflicts", []) if item.get("reason") == "duplicate_event_id_ignored"),
            None,
        )
        require(duplicate is not None, "duplicate event IDs must remain integrity conflicts")
        events.append(
            event(
                13,
                "INTEGRITY_CONFLICT_RESOLVED",
                "human-owner",
                {"conflict_id": duplicate.get("conflict_id"), "reason": "duplicate replay investigated"},
            )
        )
        resolved = derive(events)
        require(resolved.get("integrity_conflicts") == [], "explicit resolution event must clear the derived integrity blocker")

        print("Ledger race/liveness simulation PASS")
        return 0
    except AssertionError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
