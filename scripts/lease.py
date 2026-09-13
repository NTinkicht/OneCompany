#!/usr/bin/env python3
"""OneCompany implementation lease CLI with deterministic lifetime semantics.

The KERNEL-001 admission/provenance implementation is preserved in
``lease_core``. This module wraps it with lifetime authority and keeps the
existing helper API so older callers and regression tests continue to exercise
the same admission seams.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Any

import lease_core as core
import lease_lifecycle as lifecycle
import ledger_lib
from onecompany_lib import CONTROL, emergency_stop_active, load_json, save_json
from planning_lib import (
    by_id,
    dependency_ready,
    implementation_admission_violations,
    work_item_for_lease,
)

# Compatibility/test seams from the reviewed implementation.
planning_snapshot = core.planning_snapshot
admission_snapshot = core.admission_snapshot
new_lease = core.new_lease
lease_payload = core.lease_payload
_stream_from_lease = core._stream_from_lease
sync_legacy_aliases = core.sync_legacy_aliases
_format_admission_violations = core._format_admission_violations
actor_capacity_state = core.actor_capacity_state
trusted_pr_base = ledger_lib.trusted_pr_base
trusted_admission_context = ledger_lib.trusted_admission_context
list_events = ledger_lib.list_events
post_event = ledger_lib.post_event
ledger_enabled = ledger_lib.ledger_enabled
derive = lifecycle.derive_lifecycle


def authoritative(_state: dict | None = None) -> tuple[list[dict], list[dict]]:
    view = lifecycle.coordination_view()
    return (
        [
            item
            for item in view.get("active_leases", [])
            if item.get("role") == "implementation"
        ],
        view.get("integrity_conflicts", view.get("conflicts", [])),
    )


def _bind_core() -> None:
    """Forward wrapper seams into lease_core before delegated durable calls.

    Besides preserving backwards compatibility, this makes mocks hit the same
    boundary the production wrapper uses rather than silently bypassing tests.
    """
    core.derive = derive
    core.ledger_enabled = ledger_enabled
    core.list_events = list_events
    core.post_event = post_event
    core.trusted_pr_base = trusted_pr_base
    core.trusted_admission_context = trusted_admission_context
    core.authoritative = authoritative
    core.actor_capacity_state = actor_capacity_state
    core.emergency_stop_active = emergency_stop_active
    core.load_json = load_json
    core.save_json = save_json


def _active_view(
    *,
    now: dt.datetime | None = None,
) -> tuple[dict[str, Any], list[dict]]:
    view = lifecycle.coordination_view(now=now)
    active = [
        item
        for item in view.get("active_leases", [])
        if item.get("role") == "implementation"
    ]
    return view, active


def _reconcile_cache(pr: int | None = None) -> dict[str, Any]:
    """Regenerate state.json from event truth; never consume it as authority."""
    state = load_json(CONTROL / "state.json")
    view = lifecycle.coordination_view()
    active = [
        item
        for item in view.get("active_leases", [])
        if item.get("role") == "implementation"
    ]
    state["active_leases"] = active
    state["current_actor_eligibility"] = view.get("current_actor_eligibility", {})

    streams: list[dict] = []
    for lease in active:
        stream = _stream_from_lease(lease)
        lease_pr = lease.get("pr")
        if isinstance(lease_pr, int):
            pr_view = lifecycle.coordination_view(lease_pr)
            stream["material_authors"] = pr_view.get("material_authors", [])
            stream["gate"] = pr_view.get("current_gate")
        stream["expires_at"] = lease.get("expires_at")
        stream["last_progress_head"] = lease.get("last_progress_head")
        streams.append(stream)

    state["active_streams"] = streams
    sync_legacy_aliases(state)
    if len(streams) == 1:
        state["current_material_authors"] = streams[0].get("material_authors", [])
        state["current_gate"] = streams[0].get("gate")
    state["company_state"] = (
        "ACTIVE_PARALLEL_IMPLEMENTATION"
        if len(streams) > 1
        else ("ACTIVE_IMPLEMENTATION" if streams else "POST_LEASE_RECONCILE")
    )
    state["generated_or_reconciled_at"] = dt.datetime.now(
        dt.timezone.utc
    ).isoformat()
    state["note"] = (
        "Generated cache only. Implementation authority is reconstructed from "
        "coordination events; editing or deleting this file cannot grant a lease."
    )
    save_json(CONTROL / "state.json", state)
    return state


def sync_cache(_state: dict | None = None, pr: int | None = None) -> None:
    _reconcile_cache(pr)


def _local_acquire(args: argparse.Namespace) -> int:
    if emergency_stop_active():
        print(
            "REFUSED: emergency stop is active; no new implementation lease may be acquired"
        )
        return 2

    queue = load_json(CONTROL / "queue.json")
    planning = load_json(CONTROL / "planning.json")
    work_map = by_id(queue.get("work_units", []))
    candidate = work_map.get(args.wu)
    if candidate is None:
        print(f"REFUSED: work unit {args.wu} does not exist in queue")
        return 2
    if candidate.get("status") != "READY":
        print(
            f"REFUSED: work unit {args.wu} is not READY "
            f"(status={candidate.get('status')})"
        )
        return 2

    view, active = _active_view()
    integrity = view.get("integrity_conflicts", view.get("conflicts", []))
    if integrity:
        print(
            "REFUSED: coordination integrity conflicts must be reconciled first: "
            f"{integrity}"
        )
        return 2

    done = set(
        view.get(
            "verified_merged_work_units",
            view.get("merged_work_units", []),
        )
    )
    ready, missing, unsatisfied = dependency_ready(
        candidate,
        work_map,
        done,
    )
    if not ready:
        detail: list[str] = []
        if missing:
            detail.append("missing=" + ",".join(sorted(missing)))
        if unsatisfied:
            detail.append("unsatisfied=" + ",".join(sorted(unsatisfied)))
        print(
            f"REFUSED: work unit {args.wu} dependencies are not complete: "
            f"{'; '.join(detail)}"
        )
        return 2

    slots, reasons, actor_active, actor_limit = actor_capacity_state(
        args.actor,
        active,
    )
    if slots <= 0:
        print(
            f"REFUSED: actor {args.actor} is not implementation-available: "
            f"{','.join(reasons)}"
        )
        return 2

    violations = implementation_admission_violations(
        candidate,
        active,
        planning,
        work_map,
        actor=args.actor,
        actor_limit=actor_limit,
    )
    if violations:
        print(
            "REFUSED: implementation admission denied: "
            f"{_format_admission_violations(violations)}"
        )
        return 2

    lease = new_lease(
        args.actor,
        args.wu,
        args.branch,
        args.pr,
        args.start_head,
        candidate,
        work_map=work_map,
    )
    lifecycle.append_coordination_event(
        "ROLE_LEASE_ASSIGNED",
        args.actor,
        lease_payload(lease),
    )
    after = lifecycle.coordination_view()
    winner = next(
        (
            item
            for item in after.get("active_leases", [])
            if item.get("id") == lease.get("id")
        ),
        None,
    )
    if winner is None:
        print("REFUSED: lease lost canonical admission race")
        return 2

    _reconcile_cache(args.pr)
    limit = int(
        planning.get("parallel_execution", {}).get(
            "max_concurrent_implementation_streams",
            1,
        )
        or 1
    )
    print(
        f"LEASED {args.wu} to {args.actor} on {args.branch} ({lease['id']}); "
        f"active_streams={len(active) + 1}/{limit}; "
        f"actor_capacity={actor_active + 1}/{actor_limit}; "
        f"expires_at={winner.get('expires_at')}"
    )
    return 0


def _local_release(args: argparse.Namespace) -> int:
    _view, active = _active_view()
    old = next(
        (item for item in active if item.get("id") == args.lease_id),
        None,
    )
    if old is None:
        print("REFUSED: active lease not found")
        return 2
    lifecycle.append_coordination_event(
        "ROLE_LEASE_RELEASED",
        str(old.get("actor") or "system"),
        {
            "lease_id": args.lease_id,
            "pr": old.get("pr"),
            "reason": args.reason,
        },
    )
    _reconcile_cache(old.get("pr"))
    print("LEASE RELEASED")
    return 0


def _local_transfer(args: argparse.Namespace) -> int:
    if emergency_stop_active():
        print(
            "REFUSED: emergency stop is active; release/contain work instead of "
            "transferring implementation"
        )
        return 2

    view, active = _active_view()
    integrity = view.get("integrity_conflicts", view.get("conflicts", []))
    if integrity:
        print(
            "REFUSED: coordination integrity conflicts must be reconciled first: "
            f"{integrity}"
        )
        return 2

    if args.lease_id:
        old = next(
            (item for item in active if item.get("id") == args.lease_id),
            None,
        )
    elif len(active) == 1:
        old = active[0]
    else:
        old = None
    if old is None:
        print("REFUSED: requested source lease is not active or transfer is ambiguous")
        return 2
    if old.get("actor") == args.actor:
        print("REFUSED: replacement actor already holds lease")
        return 2

    queue = load_json(CONTROL / "queue.json")
    planning = load_json(CONTROL / "planning.json")
    work_map = by_id(queue.get("work_units", []))
    other_active = [
        item
        for item in active
        if item.get("id") != old.get("id")
    ]
    slots, reasons, actor_active, actor_limit = actor_capacity_state(
        args.actor,
        active,
        str(old.get("id")),
    )
    if slots <= 0:
        print(
            f"REFUSED: replacement actor {args.actor} is not implementation-available: "
            f"{','.join(reasons)}"
        )
        return 2

    item = work_item_for_lease(old, work_map)
    violations = implementation_admission_violations(
        item,
        other_active,
        planning,
        work_map,
        actor=args.actor,
        actor_limit=actor_limit,
    )
    if violations:
        print(
            "REFUSED: failover admission denied: "
            f"{_format_admission_violations(violations)}"
        )
        return 2

    replacement = new_lease(
        args.actor,
        str(old.get("work_unit")),
        str(old.get("branch")),
        old.get("pr"),
        args.current_head,
        item,
        str(old.get("id")),
    )
    payload = lease_payload(replacement) | {
        "old_lease_id": old.get("id"),
        "new_lease_id": replacement.get("id"),
        "old_actor": old.get("actor"),
        "reason": args.reason,
    }
    lifecycle.append_coordination_event(
        "ROLE_LEASE_TRANSFERRED",
        args.actor,
        payload,
    )
    after = lifecycle.coordination_view()
    winner = next(
        (
            entry
            for entry in after.get("active_leases", [])
            if entry.get("id") == replacement.get("id")
        ),
        None,
    )
    if winner is None:
        print("REFUSED: transfer did not become canonical")
        return 2

    _reconcile_cache(old.get("pr"))
    print(
        f"LEASE FAILOVER {old.get('actor')} -> {args.actor}; "
        f"WU={old.get('work_unit')} branch={old.get('branch')} pr={old.get('pr')}; "
        f"actor_capacity={actor_active + 1}/{actor_limit}; "
        f"expires_at={winner.get('expires_at')}"
    )
    return 0


def renew(args: argparse.Namespace) -> int:
    if emergency_stop_active():
        print("REFUSED: emergency stop is active; lease renewal is disabled")
        return 2

    _view, active = _active_view()
    lease = next(
        (item for item in active if item.get("id") == args.lease_id),
        None,
    )
    if lease is None:
        print(
            "REFUSED: lease is not canonical and active "
            "(it may already be expired)"
        )
        return 2

    previous = str(
        lease.get("last_progress_head")
        or lease.get("start_head")
        or ""
    )
    if ledger_enabled():
        pr = lease.get("pr")
        if not isinstance(pr, int):
            print("REFUSED: durable lease has no PR number")
            return 2
        valid, error = lifecycle.verify_pr_head_progress(
            pr,
            previous,
            args.new_head,
            cache={},
        )
        if not valid:
            print(f"REFUSED: progress is not platform-verifiable: {error}")
            return 2
    elif previous == args.new_head:
        print("REFUSED: heartbeat/same-head observation is not durable progress")
        return 2

    actor = str(lease.get("actor") or "")
    lifecycle.append_coordination_event(
        lifecycle.RENEW_EVENT,
        actor,
        lifecycle.renewal_payload(lease, args.new_head),
    )
    after = lifecycle.coordination_view()
    renewed = next(
        (
            item
            for item in after.get("active_leases", [])
            if item.get("id") == args.lease_id
        ),
        None,
    )
    if renewed is None or renewed.get("last_progress_head") != args.new_head:
        print("REFUSED: renewal did not become canonical")
        return 2

    _reconcile_cache(lease.get("pr"))
    print(
        f"LEASE RENEWED {args.lease_id}; expires_at={renewed.get('expires_at')}"
    )
    return 0


def reap(args: argparse.Namespace) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    view = lifecycle.coordination_view(now=now)
    expired = view.get("expired_leases", [])
    if args.lease_id:
        expired = [
            item
            for item in expired
            if item.get("id") == args.lease_id
        ]
    if not expired:
        print("NO EXPIRED LEASES TO REAP")
        return 0

    for lease in expired:
        lifecycle.append_coordination_event(
            lifecycle.REAP_EVENT,
            args.actor,
            lifecycle.reap_payload(lease, args.reason),
            now=now,
        )
    after = lifecycle.coordination_view(now=now)
    remaining = {
        str(item.get("id"))
        for item in after.get("expired_leases", [])
        if not args.lease_id or item.get("id") == args.lease_id
    }
    _reconcile_cache(None)
    if remaining:
        print(f"REFUSED: reap did not become canonical for {sorted(remaining)}")
        return 2
    print(f"LEASES REAPED {len(expired)}")
    return 0


def acquire(args: argparse.Namespace) -> int:
    if ledger_enabled():
        _bind_core()
        result = core.acquire(args)
        if result == 0:
            _reconcile_cache(args.pr)
        return result
    return _local_acquire(args)


def release(args: argparse.Namespace) -> int:
    if ledger_enabled():
        _bind_core()
        result = core.release(args)
        if result == 0:
            _reconcile_cache(None)
        return result
    return _local_release(args)


def transfer(args: argparse.Namespace) -> int:
    if ledger_enabled():
        _bind_core()
        result = core.transfer(args)
        if result == 0:
            _reconcile_cache(None)
        return result
    return _local_transfer(args)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    acquire_p = sub.add_parser("acquire")
    acquire_p.add_argument("--wu", required=True)
    acquire_p.add_argument("--actor", required=True)
    acquire_p.add_argument("--branch", required=True)
    acquire_p.add_argument("--start-head", required=True)
    acquire_p.add_argument("--pr", type=int)
    acquire_p.set_defaults(func=acquire)

    release_p = sub.add_parser("release")
    release_p.add_argument("--lease-id", required=True)
    release_p.add_argument("--reason", default="completed_or_failover")
    release_p.set_defaults(func=release)

    transfer_p = sub.add_parser("transfer")
    transfer_p.add_argument("--lease-id")
    transfer_p.add_argument("--actor", required=True)
    transfer_p.add_argument("--current-head", required=True)
    transfer_p.add_argument("--reason", default="capability_failover")
    transfer_p.set_defaults(func=transfer)

    renew_p = sub.add_parser("renew")
    renew_p.add_argument("--lease-id", required=True)
    renew_p.add_argument("--new-head", required=True)
    renew_p.set_defaults(func=renew)

    reap_p = sub.add_parser("reap")
    reap_p.add_argument("--lease-id")
    reap_p.add_argument("--actor", default="system-reaper")
    reap_p.add_argument("--reason", default="lease_expired")
    reap_p.set_defaults(func=reap)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
