#!/usr/bin/env python3
"""OneCompany implementation lease CLI with deterministic lifetime semantics.

The previously reviewed admission/provenance implementation lives unchanged in
``lease_core``. Durable acquire/release/transfer delegate to it while replacing
its replay view with the lifecycle-aware reducer. Local mode uses an untracked
event log and the same admission/reducer primitives; ``state.json`` is cache
only and is rebuilt after every mutation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Any

import lease_core as core
import lease_lifecycle as lifecycle
from ledger_lib import ledger_enabled
from onecompany_lib import CONTROL, emergency_stop_active, load_json, save_json
from planning_lib import (
    by_id,
    dependency_ready,
    implementation_admission_violations,
    work_item_for_lease,
)

# Preserve the exact KERNEL-001 implementation but make every durable replay it
# performs lifetime-aware. ledger_lib.derive remains the admission authority
# inside lease_lifecycle, so this assignment cannot recurse.
core.derive = lifecycle.derive_lifecycle


def _active_view(*, now: dt.datetime | None = None) -> tuple[dict[str, Any], list[dict]]:
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
        stream = core._stream_from_lease(lease)
        lease_pr = lease.get("pr")
        if isinstance(lease_pr, int):
            pr_view = lifecycle.coordination_view(lease_pr)
            stream["material_authors"] = pr_view.get("material_authors", [])
            stream["gate"] = pr_view.get("current_gate")
        stream["expires_at"] = lease.get("expires_at")
        stream["last_progress_head"] = lease.get("last_progress_head")
        streams.append(stream)
    state["active_streams"] = streams
    core.sync_legacy_aliases(state)
    if len(streams) == 1:
        state["current_material_authors"] = streams[0].get("material_authors", [])
        state["current_gate"] = streams[0].get("gate")
    state["company_state"] = (
        "ACTIVE_PARALLEL_IMPLEMENTATION"
        if len(streams) > 1
        else ("ACTIVE_IMPLEMENTATION" if streams else "POST_LEASE_RECONCILE")
    )
    state["generated_or_reconciled_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    state["note"] = (
        "Generated cache only. Implementation authority is reconstructed from "
        "coordination events; editing or deleting this file cannot grant a lease."
    )
    save_json(CONTROL / "state.json", state)
    return state


def _local_acquire(args: argparse.Namespace) -> int:
    if emergency_stop_active():
        print("REFUSED: emergency stop is active; no new implementation lease may be acquired")
        return 2
    queue = load_json(CONTROL / "queue.json")
    planning = load_json(CONTROL / "planning.json")
    work_map = by_id(queue.get("work_units", []))
    candidate = work_map.get(args.wu)
    if candidate is None:
        print(f"REFUSED: work unit {args.wu} does not exist in queue")
        return 2
    if candidate.get("status") != "READY":
        print(f"REFUSED: work unit {args.wu} is not READY (status={candidate.get('status')})")
        return 2

    view, active = _active_view()
    integrity = view.get("integrity_conflicts", view.get("conflicts", []))
    if integrity:
        print(f"REFUSED: coordination integrity conflicts must be reconciled first: {integrity}")
        return 2
    done = set(view.get("merged_work_units", []))
    ready, missing, unsatisfied = dependency_ready(candidate, work_map, done)
    if not ready:
        detail: list[str] = []
        if missing:
            detail.append("missing=" + ",".join(sorted(missing)))
        if unsatisfied:
            detail.append("unsatisfied=" + ",".join(sorted(unsatisfied)))
        print(f"REFUSED: work unit {args.wu} dependencies are not complete: {'; '.join(detail)}")
        return 2

    slots, reasons, actor_active, actor_limit = core.actor_capacity_state(args.actor, active)
    if slots <= 0:
        print(f"REFUSED: actor {args.actor} is not implementation-available: {','.join(reasons)}")
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
        print(f"REFUSED: implementation admission denied: {core._format_admission_violations(violations)}")
        return 2

    lease = core.new_lease(
        args.actor,
        args.wu,
        args.branch,
        args.pr,
        args.start_head,
        candidate,
        work_map=work_map,
    )
    lifecycle.append_coordination_event(
        "ROLE_LEASE_ASSIGNED", args.actor, core.lease_payload(lease)
    )
    after = lifecycle.coordination_view()
    winner = next(
        (item for item in after.get("active_leases", []) if item.get("id") == lease.get("id")),
        None,
    )
    if winner is None:
        print("REFUSED: lease lost canonical admission race")
        _reconcile_cache(args.pr)
        return 2
    _reconcile_cache(args.pr)
    limit = int(
        planning.get("parallel_execution", {}).get("max_concurrent_implementation_streams", 1)
        or 1
    )
    print(
        f"LEASED {args.wu} to {args.actor} on {args.branch} ({lease['id']}); "
        f"active_streams={len(active)+1}/{limit}; actor_capacity={actor_active+1}/{actor_limit}; "
        f"expires_at={winner.get('expires_at')}"
    )
    return 0


def _local_release(args: argparse.Namespace) -> int:
    _view, active = _active_view()
    old = next((item for item in active if item.get("id") == args.lease_id), None)
    if old is None:
        print("REFUSED: active lease not found")
        return 2
    lifecycle.append_coordination_event(
        "ROLE_LEASE_RELEASED",
        str(old.get("actor") or "system"),
        {"lease_id": args.lease_id, "pr": old.get("pr"), "reason": args.reason},
    )
    _reconcile_cache(old.get("pr"))
    print("LEASE RELEASED")
    return 0


def _local_transfer(args: argparse.Namespace) -> int:
    if emergency_stop_active():
        print("REFUSED: emergency stop is active; release/contain work instead of transferring implementation")
        return 2
    view, active = _active_view()
    integrity = view.get("integrity_conflicts", view.get("conflicts", []))
    if integrity:
        print(f"REFUSED: coordination integrity conflicts must be reconciled first: {integrity}")
        return 2
    if args.lease_id:
        old = next((item for item in active if item.get("id") == args.lease_id), None)
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
    other_active = [item for item in active if item.get("id") != old.get("id")]
    slots, reasons, actor_active, actor_limit = core.actor_capacity_state(
        args.actor, active, str(old.get("id"))
    )
    if slots <= 0:
        print(f"REFUSED: replacement actor {args.actor} is not implementation-available: {','.join(reasons)}")
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
        print(f"REFUSED: failover admission denied: {core._format_admission_violations(violations)}")
        return 2
    replacement = core.new_lease(
        args.actor,
        str(old.get("work_unit")),
        str(old.get("branch")),
        old.get("pr"),
        args.current_head,
        item,
        str(old.get("id")),
    )
    payload = core.lease_payload(replacement) | {
        "old_lease_id": old.get("id"),
        "new_lease_id": replacement.get("id"),
        "old_actor": old.get("actor"),
        "reason": args.reason,
    }
    lifecycle.append_coordination_event("ROLE_LEASE_TRANSFERRED", args.actor, payload)
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
        _reconcile_cache(old.get("pr"))
        return 2
    _reconcile_cache(old.get("pr"))
    print(
        f"LEASE FAILOVER {old.get('actor')} -> {args.actor}; WU={old.get('work_unit')} "
        f"branch={old.get('branch')} pr={old.get('pr')}; actor_capacity={actor_active+1}/{actor_limit}; "
        f"expires_at={winner.get('expires_at')}"
    )
    return 0


def renew(args: argparse.Namespace) -> int:
    if emergency_stop_active():
        print("REFUSED: emergency stop is active; lease renewal is disabled")
        return 2
    _view, active = _active_view()
    lease = next((item for item in active if item.get("id") == args.lease_id), None)
    if lease is None:
        print("REFUSED: lease is not canonical and active (it may already be expired)")
        return 2
    previous = str(lease.get("last_progress_head") or lease.get("start_head") or "")
    if ledger_enabled():
        pr = lease.get("pr")
        if not isinstance(pr, int):
            print("REFUSED: durable lease has no PR number")
            return 2
        valid, error = lifecycle.verify_pr_head_progress(pr, previous, args.new_head, cache={})
        if not valid:
            print(f"REFUSED: progress is not platform-verifiable: {error}")
            return 2
    elif previous == args.new_head:
        print("REFUSED: heartbeat/same-head observation is not durable progress")
        return 2

    actor = str(lease.get("actor") or "")
    payload = lifecycle.renewal_payload(lease, args.new_head)
    lifecycle.append_coordination_event(lifecycle.RENEW_EVENT, actor, payload)
    after = lifecycle.coordination_view()
    renewed = next(
        (item for item in after.get("active_leases", []) if item.get("id") == args.lease_id),
        None,
    )
    if renewed is None or renewed.get("last_progress_head") != args.new_head:
        print("REFUSED: renewal did not become canonical")
        _reconcile_cache(lease.get("pr"))
        return 2
    _reconcile_cache(lease.get("pr"))
    print(f"LEASE RENEWED {args.lease_id}; expires_at={renewed.get('expires_at')}")
    return 0


def reap(args: argparse.Namespace) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    view = lifecycle.coordination_view(now=now)
    expired = view.get("expired_leases", [])
    if args.lease_id:
        expired = [item for item in expired if item.get("id") == args.lease_id]
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
        result = core.acquire(args)
        if result == 0:
            _reconcile_cache(args.pr)
        return result
    return _local_acquire(args)


def release(args: argparse.Namespace) -> int:
    if ledger_enabled():
        result = core.release(args)
        if result == 0:
            _reconcile_cache(None)
        return result
    return _local_release(args)


def transfer(args: argparse.Namespace) -> int:
    if ledger_enabled():
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
