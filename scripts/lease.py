#!/usr/bin/env python3
"""Explicit OneCompany implementation leases with readiness/budget enforcement.

The state file is a cache; commit/reconcile durable lease changes through normal repository governance in real deployments.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid

from onecompany_lib import CONTROL, active_implementation_leases, budget_allows, load_json, save_json


def actor_eligible_for_implementation(actor_id: str) -> tuple[bool, list[str]]:
    actors = load_json(CONTROL / "actors.json")
    readiness_doc = load_json(CONTROL / "readiness.json")
    budget = load_json(CONTROL / "budget.json")
    actor = next((item for item in actors.get("actors", []) if item.get("id") == actor_id), None)
    ready = next((item for item in readiness_doc.get("actors", []) if item.get("actor_id") == actor_id), None)
    reasons: list[str] = []
    if actor is None:
        return False, ["unknown_actor"]
    if not actor.get("enabled"):
        reasons.append("disabled")
    if not actor.get("configured"):
        reasons.append("not_configured")
    if "implementation" not in actor.get("capabilities", []):
        reasons.append("implementation_not_declared")
    if not budget_allows(actor.get("cost_class", "UNKNOWN_COST"), budget):
        reasons.append("forbidden_by_budget")
    if ready is None:
        reasons.append("missing_readiness")
    else:
        if ready.get("setup_state") not in {"ready", "degraded"}:
            reasons.append(f"setup_state:{ready.get('setup_state')}")
        if "implementation" not in ready.get("verified_capabilities", []):
            reasons.append("implementation_not_verified")
        if "implementation" in ready.get("temporarily_unavailable_capabilities", []):
            reasons.append("implementation_temporarily_unavailable")
        access = ready.get("repository_access", {})
        if not access.get("read"):
            reasons.append("repository_read_not_verified")
        if not access.get("write"):
            reasons.append("repository_write_not_verified")
    return not reasons, reasons


def append_material_author(state: dict, actor_id: str) -> None:
    authors = state.setdefault("current_material_authors", [])
    if actor_id not in authors:
        authors.append(actor_id)


def new_lease(*, actor: str, wu: str, branch: str, pr: int | None, start_head: str, parent_lease_id: str | None = None) -> dict:
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
        "failover_conditions": ["quota_exhausted", "unavailable", "no_durable_progress_after_reconciliation", "human_override"],
    }
    if parent_lease_id:
        value["parent_lease_id"] = parent_lease_id
    return value


def acquire(args: argparse.Namespace) -> int:
    state = load_json(CONTROL / "state.json")
    active = active_implementation_leases(state)
    if active:
        lease = active[0]
        print(f"REFUSED: implementation lease already active for {lease.get('work_unit')} by {lease.get('actor')}")
        return 2

    eligible, reasons = actor_eligible_for_implementation(args.actor)
    if not eligible:
        print(f"REFUSED: actor {args.actor} is not implementation-ready: {','.join(reasons)}")
        return 2

    lease = new_lease(actor=args.actor, wu=args.wu, branch=args.branch, pr=args.pr, start_head=args.start_head)
    state.setdefault("active_leases", []).append(lease)
    append_material_author(state, args.actor)  # conservative: implementation lease implies potential material authorship
    state["current_work_unit"] = args.wu
    if args.pr is not None:
        state["current_pr"] = args.pr
        state["current_pr_head"] = args.start_head
    state["current_gate"] = None
    state["company_state"] = "ACTIVE_IMPLEMENTATION"
    save_json(CONTROL / "state.json", state)
    print(f"LEASED {args.wu} to {args.actor} on {args.branch} ({lease['id']})")
    return 0


def release(args: argparse.Namespace) -> int:
    state = load_json(CONTROL / "state.json")
    found = False
    for lease in state.get("active_leases", []):
        if lease.get("id") == args.lease_id and lease.get("status") == "active":
            lease["status"] = "released"
            lease["released_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            lease["release_reason"] = args.reason
            found = True
    if not found:
        print("REFUSED: active lease not found")
        return 2
    state["company_state"] = "INITIALIZING" if not active_implementation_leases(state) else state["company_state"]
    save_json(CONTROL / "state.json", state)
    print("LEASE RELEASED")
    return 0


def transfer(args: argparse.Namespace) -> int:
    state = load_json(CONTROL / "state.json")
    active = active_implementation_leases(state)
    if len(active) != 1:
        print(f"REFUSED: transfer requires exactly one active implementation lease; found {len(active)}")
        return 2
    old = active[0]
    eligible, reasons = actor_eligible_for_implementation(args.actor)
    if not eligible:
        print(f"REFUSED: replacement actor {args.actor} is not implementation-ready: {','.join(reasons)}")
        return 2
    if old.get("actor") == args.actor:
        print("REFUSED: replacement actor already holds the lease")
        return 2

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    old["status"] = "released"
    old["released_at"] = now
    old["release_reason"] = args.reason
    replacement = new_lease(
        actor=args.actor,
        wu=str(old.get("work_unit")),
        branch=str(old.get("branch")),
        pr=old.get("pr"),
        start_head=args.current_head,
        parent_lease_id=str(old.get("id")),
    )
    state.setdefault("active_leases", []).append(replacement)
    append_material_author(state, args.actor)
    state["current_pr_head"] = args.current_head if old.get("pr") is not None else state.get("current_pr_head")
    state["current_gate"] = None
    state["company_state"] = "ACTIVE_IMPLEMENTATION"
    save_json(CONTROL / "state.json", state)
    print(f"LEASE FAILOVER {old.get('actor')} -> {args.actor}; preserved WU={old.get('work_unit')} branch={old.get('branch')} pr={old.get('pr')}")
    print(f"NEW LEASE {replacement['id']} parent={old.get('id')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("acquire")
    a.add_argument("--wu", required=True)
    a.add_argument("--actor", required=True)
    a.add_argument("--branch", required=True)
    a.add_argument("--start-head", required=True)
    a.add_argument("--pr", type=int)
    a.set_defaults(func=acquire)

    r = sub.add_parser("release")
    r.add_argument("--lease-id", required=True)
    r.add_argument("--reason", default="completed_or_failover")
    r.set_defaults(func=release)

    t = sub.add_parser("transfer", help="Atomically fail over the active implementation lease while preserving the stream")
    t.add_argument("--actor", required=True, help="Replacement actor")
    t.add_argument("--current-head", required=True, help="Exact canonical branch/PR head at transfer time")
    t.add_argument("--reason", default="capability_failover")
    t.set_defaults(func=transfer)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
