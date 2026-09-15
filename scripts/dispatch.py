#!/usr/bin/env python3
"""Resolve an executable dispatch/wake path for an already-routed actor."""
from __future__ import annotations

import argparse
import json
import sys

from lease_lifecycle import coordination_view
from ledger_lib import ledger_enabled
from onecompany_lib import CONTROL, emergency_stop_active, load_json

WRITE_CAPABILITIES = {"implementation", "ci_remediation", "merge_execution"}


def resolve_dispatch(
    actor_id: str,
    capability: str,
    *,
    unattended: bool = False,
    lease_id: str | None = None,
) -> dict:
    """Return the live dispatch-resolution result without invoking a worker."""
    actors = {
        item["id"]: item
        for item in load_json(CONTROL / "actors.json").get("actors", [])
        if item.get("id")
    }
    readiness = {
        item["actor_id"]: item
        for item in load_json(CONTROL / "readiness.json").get("actors", [])
        if item.get("actor_id")
    }
    dispatch = {
        item["actor_id"]: item
        for item in load_json(CONTROL / "dispatch.json").get("actors", [])
        if item.get("actor_id")
    }
    reasons: list[str] = []

    if emergency_stop_active() and (unattended or capability in WRITE_CAPABILITIES):
        reasons.append("emergency_stop_active")

    actor = actors.get(actor_id)
    ready = readiness.get(actor_id)
    entry = dispatch.get(actor_id)
    if not actor:
        reasons.append("unknown_actor")
    else:
        if not actor.get("enabled") or not actor.get("configured"):
            reasons.append("actor_not_enabled_and_configured")
        if capability not in set(actor.get("capabilities", [])):
            reasons.append("capability_not_declared")

    if not ready:
        reasons.append("missing_readiness")
    else:
        if ready.get("setup_state") not in {"ready", "degraded"}:
            reasons.append("actor_not_ready")
        if capability not in set(ready.get("verified_capabilities", [])):
            reasons.append("capability_not_verified")
        if capability in set(ready.get("temporarily_unavailable_capabilities", [])):
            reasons.append("capability_temporarily_unavailable")
        if unattended and (
            ready.get("unattended", {}).get("configured") is not True
            or ready.get("unattended", {}).get("verified") is not True
        ):
            reasons.append("unattended_readiness_not_verified")

    if unattended and capability in {"implementation", "ci_remediation"}:
        if not ledger_enabled():
            reasons.append("durable_ledger_required_for_unattended_write")
        elif not lease_id:
            reasons.append("active_lease_id_required_for_unattended_write")
        else:
            try:
                view = coordination_view()
                lease = next(
                    (
                        item
                        for item in view.get("active_leases", [])
                        if item.get("id") == lease_id
                    ),
                    None,
                )
                if not lease:
                    reasons.append("lease_not_canonical_active_and_unexpired")
                elif lease.get("actor") != actor_id:
                    reasons.append("lease_actor_mismatch")
            except Exception as exc:
                reasons.append(f"ledger_unavailable:{exc}")

    mechanisms: list[dict] = []
    if entry:
        for mechanism in entry.get("mechanisms", []):
            if (
                mechanism.get("configured")
                and capability in set(mechanism.get("capabilities", []))
                and (not unattended or mechanism.get("unattended"))
            ):
                mechanisms.append(
                    {
                        "id": mechanism.get("id"),
                        "kind": mechanism.get("kind"),
                        "unattended": mechanism.get("unattended"),
                        "invocation_hint": mechanism.get("invocation_hint"),
                        "evidence": mechanism.get("evidence", []),
                    }
                )
    else:
        reasons.append("missing_dispatch_record")
    if not mechanisms:
        reasons.append("no_configured_execution_mechanism")

    return {
        "actor": actor_id,
        "capability": capability,
        "unattended_required": unattended,
        "status": "DISPATCH_READY" if not reasons and mechanisms else "CAPACITY_BLOCKED",
        "mechanisms": mechanisms,
        "reasons": sorted(set(reasons)),
    }


def main() -> int:
    """CLI wrapper for dispatch resolution; resolution never starts a worker."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--unattended", action="store_true")
    parser.add_argument("--lease-id")
    args = parser.parse_args()

    payload = resolve_dispatch(
        args.actor,
        args.capability,
        unattended=args.unattended,
        lease_id=args.lease_id,
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "DISPATCH_READY" else 2


if __name__ == "__main__":
    sys.exit(main())
