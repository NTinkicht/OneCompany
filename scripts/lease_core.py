#!/usr/bin/env python3
"""Explicit OneCompany implementation leases with durable admission proof."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid

from capacity_lib import implementation_active_count, implementation_availability, implementation_capacity_limit
from ledger_lib import (
    derive,
    ledger_enabled,
    list_events,
    post_event,
    trusted_admission_context,
    trusted_pr_base,
)
from onecompany_lib import CONTROL, active_implementation_leases, emergency_stop_active, load_json, save_json
from planning_lib import (
    by_id,
    dependency_closure,
    dependency_ready,
    implementation_admission_violations,
    work_item_for_lease,
)

ADMISSION_SCHEMA = "onecompany-lease-admission-v1"


def actor_capacity_state(
    actor_id: str,
    active: list[dict],
    exclude_lease_id: str | None = None,
) -> tuple[int, list[str], int, int]:
    actors = load_json(CONTROL / "actors.json")
    readiness_doc = load_json(CONTROL / "readiness.json")
    budget = load_json(CONTROL / "budget.json")
    actor = next((item for item in actors.get("actors", []) if item.get("id") == actor_id), None)
    if actor is None:
        return 0, ["unknown_actor"], 0, 0
    ready = next(
        (item for item in readiness_doc.get("actors", []) if item.get("actor_id") == actor_id),
        None,
    )
    slots, reasons = implementation_availability(
        actor,
        ready,
        budget,
        active,
        exclude_lease_id=exclude_lease_id,
    )
    current = implementation_active_count(actor_id, active, exclude_lease_id)
    limit = implementation_capacity_limit(ready)
    return slots, sorted(set(reasons)), current, limit


def planning_snapshot(item: dict, work_map: dict[str, dict] | None = None) -> dict:
    direct_dependencies = [str(value) for value in item.get("dependencies", [])]
    snapshot = {
        "write_scope": list(item.get("write_scope", [])),
        "resource_locks": list(item.get("resource_locks", [])),
        "parallelism": item.get("parallelism", "auto"),
        "risk_class": item.get("risk_class", "MEDIUM"),
        "dependencies": direct_dependencies,
    }
    if work_map and item.get("id"):
        snapshot["dependency_closure"] = sorted(
            dependency_closure(work_map, str(item.get("id")))
        )
    else:
        existing_closure = item.get("dependency_closure")
        if isinstance(existing_closure, list):
            snapshot["dependency_closure"] = sorted(
                {str(value) for value in existing_closure if value}
            )
    return snapshot


def admission_snapshot(
    *,
    actor: str,
    actor_limit: int,
    item: dict,
    dependencies_complete: bool,
    transfer_source_lease_id: str | None = None,
    trusted_ref: str | None = None,
    policy_blobs: dict | None = None,
    actor_eligible: bool = True,
    actor_ineligibility_reasons: list[str] | None = None,
) -> dict:
    """Record descriptive facts plus the independently verifiable trusted ref."""
    value = {
        "schema": ADMISSION_SCHEMA,
        "actor": actor,
        "actor_eligible": bool(actor_eligible),
        "actor_ineligibility_reasons": sorted(set(actor_ineligibility_reasons or [])),
        "actor_limit": int(actor_limit),
        "dependencies": sorted({str(value) for value in item.get("dependencies", []) if value}),
        "dependencies_complete": bool(dependencies_complete),
        "transfer_source_lease_id": transfer_source_lease_id,
        "dependencies_inherited_from_source": transfer_source_lease_id is not None,
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if trusted_ref is not None:
        value["trusted_ref"] = trusted_ref
    if policy_blobs is not None:
        value["policy_blobs"] = dict(policy_blobs)
    return value


def new_lease(
    actor: str,
    wu: str,
    branch: str,
    pr: int | None,
    start_head: str,
    item: dict,
    parent_lease_id: str | None = None,
    work_map: dict[str, dict] | None = None,
    admission: dict | None = None,
) -> dict:
    value = {
        "id": str(uuid.uuid4()),
        "work_unit": wu,
        "role": "implementation",
        "actor": actor,
        "branch": branch,
        "pr": pr,
        "start_head": start_head,
        "status": "active",
        "granted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "planning_snapshot": planning_snapshot(item, work_map),
        "failover_conditions": [
            "quota_exhausted",
            "unavailable",
            "no_durable_progress_after_reconciliation",
            "human_override",
        ],
    }
    if parent_lease_id:
        value["parent_lease_id"] = parent_lease_id
    if admission:
        value["admission_snapshot"] = admission
    return value


def lease_payload(lease: dict) -> dict:
    payload = {
        "lease_id": lease.get("id"),
        "role": lease.get("role"),
        "work_unit": lease.get("work_unit"),
        "branch": lease.get("branch"),
        "pr": lease.get("pr"),
        "start_head": lease.get("start_head"),
        "parent_lease_id": lease.get("parent_lease_id"),
        "planning_snapshot": lease.get("planning_snapshot", {}),
    }
    if isinstance(lease.get("admission_snapshot"), dict):
        payload["admission_snapshot"] = lease["admission_snapshot"]
    return payload


def authoritative(state: dict) -> tuple[list[dict], list[dict]]:
    if ledger_enabled():
        view = derive(list_events())
        return (
            [
                item
                for item in view.get("active_leases", [])
                if item.get("role") == "implementation"
            ],
            view.get("integrity_conflicts", view.get("conflicts", [])),
        )
    return active_implementation_leases(state), []


def _stream_from_lease(lease: dict) -> dict:
    actor = lease.get("actor")
    return {
        "work_unit": lease.get("work_unit"),
        "lease_id": lease.get("id"),
        "actor": actor,
        "branch": lease.get("branch"),
        "pr": lease.get("pr"),
        "head": lease.get("start_head"),
        "base_sha": None,
        "status": "ACTIVE_IMPLEMENTATION",
        "gate": None,
        "material_authors": [actor] if isinstance(actor, str) and actor else [],
        "open_blockers": [],
        "human_decision_required": False,
    }


def sync_legacy_aliases(state: dict) -> None:
    active = [
        item
        for item in state.get("active_leases", [])
        if item.get("status") == "active" and item.get("role") == "implementation"
    ]
    if len(active) == 1:
        lease = active[0]
        state["current_work_unit"] = lease.get("work_unit")
        state["current_pr"] = lease.get("pr")
        state["current_pr_head"] = lease.get("start_head")
    else:
        state["current_work_unit"] = None
        state["current_pr"] = None
        state["current_pr_head"] = None
        state["current_material_authors"] = []
        state["current_gate"] = None


def sync_cache(state: dict, pr: int | None) -> None:
    if ledger_enabled():
        events = list_events()
        global_view = derive(events)
        state["active_leases"] = global_view.get("active_leases", [])
        state["current_actor_eligibility"] = global_view.get("current_actor_eligibility", {})
        if pr is not None:
            pr_view = derive(events, pr)
            for stream in state.setdefault("active_streams", []):
                if stream.get("pr") == pr:
                    stream["material_authors"] = pr_view.get("material_authors", [])
                    stream["gate"] = pr_view.get("current_gate")
    existing = {
        stream.get("lease_id"): stream for stream in state.setdefault("active_streams", [])
    }
    streams: list[dict] = []
    for lease in state.get("active_leases", []):
        if lease.get("status") != "active" or lease.get("role") != "implementation":
            continue
        stream = existing.get(lease.get("id"), _stream_from_lease(lease))
        stream.setdefault("open_blockers", [])
        stream.setdefault("human_decision_required", False)
        stream.setdefault("base_sha", None)
        stream.setdefault(
            "material_authors", [lease.get("actor")] if lease.get("actor") else []
        )
        stream.update(
            {
                "actor": lease.get("actor"),
                "branch": lease.get("branch"),
                "pr": lease.get("pr"),
                "work_unit": lease.get("work_unit"),
            }
        )
        streams.append(stream)
    state["active_streams"] = streams
    sync_legacy_aliases(state)
    if len(streams) == 1:
        state["current_material_authors"] = streams[0].get(
            "material_authors", state.get("current_material_authors", [])
        )
        state["current_gate"] = streams[0].get("gate", state.get("current_gate"))


def _format_admission_violations(violations: list[dict]) -> str:
    details: list[str] = []
    for item in violations:
        reason = str(item.get("reason") or "unknown")
        conflict_details = item.get("details")
        if isinstance(conflict_details, list) and conflict_details:
            reason += "[" + ",".join(str(value) for value in conflict_details) + "]"
        with_wu = item.get("with_work_unit")
        if with_wu:
            reason += f"@{with_wu}"
        details.append(reason)
    return "; ".join(details)


def _base_emergency_stop_active(context: dict) -> bool:
    config = context.get("config")
    if not isinstance(config, dict):
        return False
    safety = config.get("safety")
    return isinstance(safety, dict) and safety.get("emergency_stop") is True


def _durable_dependency_check(
    candidate: dict,
    work_map: dict[str, dict],
    durable_done: set[str],
) -> tuple[bool, list[str]]:
    candidate_id = str(candidate.get("id") or "")
    if candidate_id and candidate_id in work_map:
        required = dependency_closure(work_map, candidate_id)
    else:
        snapshot_closure = candidate.get("dependency_closure")
        if isinstance(snapshot_closure, list):
            required = {str(value) for value in snapshot_closure if value}
        else:
            required = {str(value) for value in candidate.get("dependencies", []) if value}
    unsatisfied = sorted(required - durable_done)
    return not unsatisfied, unsatisfied


def acquire(args: argparse.Namespace) -> int:
    if emergency_stop_active():
        print("REFUSED: emergency stop is active; no new implementation lease may be acquired")
        return 2
    state = load_json(CONTROL / "state.json")
    local_queue = load_json(CONTROL / "queue.json")
    local_planning = load_json(CONTROL / "planning.json")
    local_work_map = by_id(local_queue.get("work_units", []))
    local_candidate = local_work_map.get(args.wu)
    if local_candidate is None:
        print(f"REFUSED: work unit {args.wu} does not exist in queue")
        return 2
    if ledger_enabled() and args.pr is None:
        print("REFUSED: durable autonomous implementation lease requires a PR number")
        return 2

    active, integrity_conflicts = authoritative(state)
    if integrity_conflicts:
        print(
            "REFUSED: durable coordination integrity conflicts must be reconciled first: "
            f"{integrity_conflicts}"
        )
        return 2

    durable_done: set[str] = set()
    trusted_ref: str | None = None
    policy_blobs: dict | None = None
    if ledger_enabled():
        try:
            events = list_events()
            durable_done = set(derive(events).get("verified_merged_work_units", []))
            trusted_ref = trusted_pr_base(int(args.pr))
            context, context_error = trusted_admission_context(
                trusted_ref, args.actor, args.wu, active, pr=int(args.pr)
            )
            if context is None:
                print(f"REFUSED: cannot verify base-trusted lease admission: {context_error}")
                return 2
            if _base_emergency_stop_active(context):
                print(
                    "REFUSED: base-trusted emergency stop is active; "
                    "no new implementation lease may be acquired"
                )
                return 2
            candidate = context["work_item"]
            work_map = context["work_map"]
            planning = context["planning"]
            policy_blobs = context["policy_blobs"]
            actor_limit = int(context.get("actor_limit") or 0)
            actor_active = implementation_active_count(args.actor, active)
            if not context.get("actor_eligible"):
                print(
                    f"REFUSED: actor {args.actor} is not base-trusted implementation-eligible: "
                    f"{','.join(context.get('actor_ineligibility_reasons', []))}"
                )
                return 2
            if actor_limit <= actor_active:
                print(
                    f"REFUSED: actor {args.actor} has no base-trusted implementation capacity: "
                    f"{actor_active}/{actor_limit}"
                )
                return 2
            durable_ready, durable_unsatisfied = _durable_dependency_check(
                candidate,
                work_map,
                durable_done,
            )
            if not durable_ready:
                print(
                    f"REFUSED: work unit {args.wu} lacks durable MERGED dependency evidence: "
                    f"{','.join(durable_unsatisfied)}"
                )
                return 2
        except Exception as exc:
            print(f"REFUSED: cannot verify durable admission state: {exc}")
            return 2
    else:
        candidate = local_candidate
        work_map = local_work_map
        planning = local_planning
        if candidate.get("status") != "READY":
            print(
                f"REFUSED: work unit {args.wu} is not READY "
                f"(status={candidate.get('status')})"
            )
            return 2
        ready, missing, unsatisfied = dependency_ready(candidate, work_map, durable_done)
        if not ready:
            detail = []
            if missing:
                detail.append("missing=" + ",".join(sorted(missing)))
            if unsatisfied:
                detail.append("unsatisfied=" + ",".join(sorted(unsatisfied)))
            print(
                f"REFUSED: work unit {args.wu} dependencies are not complete: "
                f"{'; '.join(detail)}"
            )
            return 2
        slots, reasons, actor_active, actor_limit = actor_capacity_state(args.actor, active)
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

    frozen = None
    if ledger_enabled():
        frozen = admission_snapshot(
            actor=args.actor,
            actor_limit=actor_limit,
            item=candidate,
            dependencies_complete=True,
            trusted_ref=trusted_ref,
            policy_blobs=policy_blobs,
            actor_eligible=True,
            actor_ineligibility_reasons=[],
        )
    lease = new_lease(
        args.actor,
        args.wu,
        args.branch,
        args.pr,
        args.start_head,
        candidate,
        work_map=work_map,
        admission=frozen,
    )
    if ledger_enabled():
        try:
            post_event("ROLE_LEASE_ASSIGNED", args.actor, lease_payload(lease))
            winner = next(
                (
                    item
                    for item in derive(list_events()).get("active_leases", [])
                    if item.get("id") == lease.get("id")
                ),
                None,
            )
            if not winner:
                print("REFUSED: lease lost concurrent claim/conflict/capacity race")
                return 2
        except Exception as exc:
            print(f"REFUSED: durable lease record failed: {exc}")
            return 2

    state.setdefault("active_leases", []).append(lease)
    state.setdefault("active_streams", []).append(_stream_from_lease(lease))
    sync_cache(state, args.pr)
    state["company_state"] = (
        "ACTIVE_PARALLEL_IMPLEMENTATION" if len(active) + 1 > 1 else "ACTIVE_IMPLEMENTATION"
    )
    save_json(CONTROL / "state.json", state)
    limit = int(
        planning.get("parallel_execution", {}).get("max_concurrent_implementation_streams", 1)
        or 1
    )
    print(
        f"LEASED {args.wu} to {args.actor} on {args.branch} ({lease['id']}); "
        f"active_streams={len(active)+1}/{limit}; actor_capacity={actor_active+1}/{actor_limit}"
    )
    return 0


def release(args: argparse.Namespace) -> int:
    state = load_json(CONTROL / "state.json")
    active, _ = authoritative(state)
    old = next((item for item in active if item.get("id") == args.lease_id), None)
    if not old:
        print("REFUSED: active lease not found")
        return 2
    if ledger_enabled():
        try:
            post_event(
                "ROLE_LEASE_RELEASED",
                str(old.get("actor") or "system"),
                {"lease_id": args.lease_id, "pr": old.get("pr"), "reason": args.reason},
            )
        except Exception as exc:
            print(f"REFUSED: durable lease release failed: {exc}")
            return 2
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for lease in state.get("active_leases", []):
        if lease.get("id") == args.lease_id and lease.get("status") == "active":
            lease["status"] = "released"
            lease["released_at"] = now
            lease["release_reason"] = args.reason
    state["active_streams"] = [
        stream
        for stream in state.get("active_streams", [])
        if stream.get("lease_id") != args.lease_id
    ]
    sync_cache(state, old.get("pr"))
    state["company_state"] = (
        "ACTIVE_PARALLEL_IMPLEMENTATION"
        if len(state.get("active_streams", [])) > 1
        else (
            "ACTIVE_IMPLEMENTATION"
            if state.get("active_streams")
            else "POST_LEASE_RECONCILE"
        )
    )
    save_json(CONTROL / "state.json", state)
    print("LEASE RELEASED")
    return 0


def transfer(args: argparse.Namespace) -> int:
    if emergency_stop_active():
        print(
            "REFUSED: emergency stop is active; release/contain work instead of "
            "transferring implementation"
        )
        return 2
    state = load_json(CONTROL / "state.json")
    local_queue = load_json(CONTROL / "queue.json")
    local_planning = load_json(CONTROL / "planning.json")
    local_work_map = by_id(local_queue.get("work_units", []))
    active, integrity_conflicts = authoritative(state)
    if integrity_conflicts:
        print(
            "REFUSED: durable coordination integrity conflicts must be reconciled first: "
            f"{integrity_conflicts}"
        )
        return 2
    if args.lease_id:
        old = next((item for item in active if item.get("id") == args.lease_id), None)
        if old is None:
            print("REFUSED: requested source lease is not active")
            return 2
    elif len(active) == 1:
        old = active[0]
    else:
        print(
            f"REFUSED: transfer is ambiguous with {len(active)} active implementation "
            "leases; pass --lease-id"
        )
        return 2
    if old.get("actor") == args.actor:
        print("REFUSED: replacement actor already holds lease")
        return 2

    other_active = [entry for entry in active if entry.get("id") != old.get("id")]
    trusted_ref: str | None = None
    policy_blobs: dict | None = None
    if ledger_enabled():
        pr = old.get("pr")
        if not isinstance(pr, int):
            print("REFUSED: durable failover source lease has no PR number")
            return 2
        try:
            trusted_ref = trusted_pr_base(pr)
            context, context_error = trusted_admission_context(
                trusted_ref, args.actor, None, other_active, pr=pr
            )
            if context is None:
                print(f"REFUSED: cannot verify base-trusted failover admission: {context_error}")
                return 2
            if _base_emergency_stop_active(context):
                print(
                    "REFUSED: base-trusted emergency stop is active; "
                    "release/contain work instead of transferring implementation"
                )
                return 2
            if not context.get("actor_eligible"):
                print(
                    f"REFUSED: replacement actor {args.actor} is not base-trusted implementation-eligible: "
                    f"{','.join(context.get('actor_ineligibility_reasons', []))}"
                )
                return 2
            actor_limit = int(context.get("actor_limit") or 0)
            actor_active = implementation_active_count(
                args.actor, active, str(old.get("id"))
            )
            if actor_limit <= actor_active:
                print(
                    f"REFUSED: replacement actor {args.actor} has no base-trusted implementation capacity: "
                    f"{actor_active}/{actor_limit}"
                )
                return 2
            planning = context["planning"]
            policy_blobs = context["policy_blobs"]
            item = {"id": old.get("work_unit"), **(old.get("planning_snapshot") or {})}
            work_map = None
        except Exception as exc:
            print(f"REFUSED: cannot verify durable failover admission: {exc}")
            return 2
    else:
        slots, reasons, actor_active, actor_limit = actor_capacity_state(
            args.actor, active, str(old.get("id"))
        )
        if slots <= 0:
            print(
                f"REFUSED: replacement actor {args.actor} is not implementation-available: "
                f"{','.join(reasons)}"
            )
            return 2
        planning = local_planning
        work_map = local_work_map
        item = work_item_for_lease(old, local_work_map)

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
            f"REFUSED: failover admission denied: {_format_admission_violations(violations)}"
        )
        return 2

    frozen = None
    if ledger_enabled():
        frozen = admission_snapshot(
            actor=args.actor,
            actor_limit=actor_limit,
            item=item,
            dependencies_complete=True,
            transfer_source_lease_id=str(old.get("id")),
            trusted_ref=trusted_ref,
            policy_blobs=policy_blobs,
            actor_eligible=True,
            actor_ineligibility_reasons=[],
        )
    replacement = new_lease(
        args.actor,
        str(old.get("work_unit")),
        str(old.get("branch")),
        old.get("pr"),
        args.current_head,
        item,
        str(old.get("id")),
        admission=frozen,
    )
    payload = lease_payload(replacement) | {
        "old_lease_id": old.get("id"),
        "new_lease_id": replacement.get("id"),
        "old_actor": old.get("actor"),
        "reason": args.reason,
    }
    if ledger_enabled():
        try:
            post_event("ROLE_LEASE_TRANSFERRED", args.actor, payload)
            winner = next(
                (
                    item
                    for item in derive(list_events()).get("active_leases", [])
                    if item.get("id") == replacement.get("id")
                ),
                None,
            )
            if not winner:
                print("REFUSED: durable transfer did not become canonical")
                return 2
        except Exception as exc:
            print(f"REFUSED: durable failover record failed: {exc}")
            return 2

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for lease in state.get("active_leases", []):
        if lease.get("id") == old.get("id") and lease.get("status") == "active":
            lease["status"] = "released"
            lease["released_at"] = now
            lease["release_reason"] = args.reason
    state.setdefault("active_leases", []).append(replacement)
    old_stream = next(
        (
            stream
            for stream in state.get("active_streams", [])
            if stream.get("lease_id") == old.get("id")
        ),
        None,
    )
    state["active_streams"] = [
        stream
        for stream in state.get("active_streams", [])
        if stream.get("lease_id") != old.get("id")
    ]
    new_stream = _stream_from_lease(replacement)
    authors = set(new_stream.get("material_authors", []))
    if old.get("actor"):
        authors.add(str(old.get("actor")))
    if old_stream:
        authors.update(
            str(value) for value in old_stream.get("material_authors", []) if value
        )
        new_stream["open_blockers"] = old_stream.get("open_blockers", [])
        new_stream["human_decision_required"] = old_stream.get(
            "human_decision_required", False
        )
        new_stream["base_sha"] = old_stream.get("base_sha")
    new_stream["material_authors"] = sorted(authors)
    state.setdefault("active_streams", []).append(new_stream)
    sync_cache(state, old.get("pr"))
    state["company_state"] = (
        "ACTIVE_PARALLEL_IMPLEMENTATION"
        if len(state.get("active_streams", [])) > 1
        else "ACTIVE_IMPLEMENTATION"
    )
    save_json(CONTROL / "state.json", state)
    print(
        f"LEASE FAILOVER {old.get('actor')} -> {args.actor}; WU={old.get('work_unit')} "
        f"branch={old.get('branch')} pr={old.get('pr')}; "
        f"actor_capacity={actor_active+1}/{actor_limit}"
    )
    return 0


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
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
