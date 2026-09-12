#!/usr/bin/env python3
"""Resolve an executable dispatch/wake path for an already-routed actor."""
from __future__ import annotations

import argparse
import json
import sys

from onecompany_lib import CONTROL, load_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--unattended", action="store_true", help="Require an unattended execution mechanism")
    args = parser.parse_args()

    actors = {item["id"]: item for item in load_json(CONTROL / "actors.json").get("actors", []) if item.get("id")}
    readiness = {item["actor_id"]: item for item in load_json(CONTROL / "readiness.json").get("actors", []) if item.get("actor_id")}
    dispatch = {item["actor_id"]: item for item in load_json(CONTROL / "dispatch.json").get("actors", []) if item.get("actor_id")}

    actor = actors.get(args.actor)
    ready = readiness.get(args.actor)
    entry = dispatch.get(args.actor)
    reasons: list[str] = []

    if not actor:
        reasons.append("unknown_actor")
    else:
        if not actor.get("enabled") or not actor.get("configured"):
            reasons.append("actor_not_enabled_and_configured")
        if args.capability not in set(actor.get("capabilities", [])):
            reasons.append("capability_not_declared")

    if not ready:
        reasons.append("missing_readiness")
    else:
        if ready.get("setup_state") not in {"ready", "degraded"}:
            reasons.append("actor_not_ready")
        if args.capability not in set(ready.get("verified_capabilities", [])):
            reasons.append("capability_not_verified")
        if args.capability in set(ready.get("temporarily_unavailable_capabilities", [])):
            reasons.append("capability_temporarily_unavailable")
        if args.unattended:
            unattended = ready.get("unattended", {})
            if unattended.get("configured") is not True or unattended.get("verified") is not True:
                reasons.append("unattended_readiness_not_verified")

    mechanisms = []
    if entry:
        for mechanism in entry.get("mechanisms", []):
            if not mechanism.get("configured"):
                continue
            if args.capability not in set(mechanism.get("capabilities", [])):
                continue
            if args.unattended and not mechanism.get("unattended"):
                continue
            mechanisms.append({
                "id": mechanism.get("id"),
                "kind": mechanism.get("kind"),
                "unattended": mechanism.get("unattended"),
                "invocation_hint": mechanism.get("invocation_hint"),
                "evidence": mechanism.get("evidence", []),
            })
    else:
        reasons.append("missing_dispatch_record")

    if not mechanisms:
        reasons.append("no_configured_execution_mechanism")

    payload = {
        "actor": args.actor,
        "capability": args.capability,
        "unattended_required": args.unattended,
        "status": "DISPATCH_READY" if not reasons and mechanisms else "CAPACITY_BLOCKED",
        "mechanisms": mechanisms,
        "reasons": sorted(set(reasons)),
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "DISPATCH_READY" else 2


if __name__ == "__main__":
    sys.exit(main())
