#!/usr/bin/env python3
"""Local helper for explicit OneCompany implementation leases.

The state file is a cache; commit lease changes through normal repository review in real deployments.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid

from onecompany_lib import CONTROL, active_implementation_leases, load_json, save_json


def acquire(args: argparse.Namespace) -> int:
    state = load_json(CONTROL / "state.json")
    active = active_implementation_leases(state)
    if active:
        lease = active[0]
        print(f"REFUSED: implementation lease already active for {lease.get('work_unit')} by {lease.get('actor')}")
        return 2
    lease = {
        "id": str(uuid.uuid4()),
        "work_unit": args.wu,
        "role": "implementation",
        "actor": args.actor,
        "branch": args.branch,
        "pr": args.pr,
        "start_head": args.start_head,
        "status": "active",
        "granted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "failover_conditions": ["quota_exhausted", "unavailable", "no_durable_progress", "human_override"],
    }
    state.setdefault("active_leases", []).append(lease)
    state["current_work_unit"] = args.wu
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
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
