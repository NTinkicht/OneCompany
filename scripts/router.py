#!/usr/bin/env python3
"""Choose eligible actors after capability, readiness, budget, capacity, dispatch and authorship filters."""
from __future__ import annotations

import argparse
import json
import sys

from capacity_lib import configured_dispatch_exists, implementation_availability
from ledger_lib import derive, ledger_enabled, list_events
from onecompany_lib import CONTROL, active_implementation_leases, budget_allows, load_json

WRITE_CAPS = {"implementation", "ci_remediation"}
REVIEW_CAPS = {"code_review", "security_review"}
MERGE_CAPS = {"merge_execution"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", action="append", required=True, help="Required capability; repeatable")
    parser.add_argument("--exclude-author", action="append", default=[], help="Additional actor ID materially conflicted for independent gate")
    parser.add_argument("--for-independent-gate", action="store_true")
    parser.add_argument("--pr", type=int, help="PR whose authorship should be excluded for independent review")
    parser.add_argument("--unattended", action="store_true", help="Require a verified configured unattended execution path")
    args = parser.parse_args()

    actors_doc = load_json(CONTROL / "actors.json")
    readiness_doc = load_json(CONTROL / "readiness.json")
    routing_doc = load_json(CONTROL / "routing.json")
    dispatch_doc = load_json(CONTROL / "dispatch.json")
    budget = load_json(CONTROL / "budget.json")
    state = load_json(CONTROL / "state.json")
    readiness = {item.get("actor_id"): item for item in readiness_doc.get("actors", [])}
    required = set(args.capability)

    active = active_implementation_leases(state)
    durable_events: list[dict] | None = None
    if ledger_enabled():
        try:
            durable_events = list_events()
            active = [
                item
                for item in derive(durable_events).get("active_leases", [])
                if item.get("role") == "implementation"
            ]
        except Exception as exc:
            print(json.dumps({
                "status": "BLOCKED_LEDGER_UNAVAILABLE",
                "error": str(exc),
                "eligible": [],
                "note": "Routing fails closed when durable coordination truth cannot be read.",
            }, indent=2))
            return 2

    excluded = set(args.exclude_author)
    if args.for_independent_gate:
        if args.pr is None and len(state.get("active_streams", [])) > 1:
            print(json.dumps({
                "status": "BLOCKED_AMBIGUOUS_REVIEW_STREAM",
                "eligible": [],
                "note": "Pass --pr when more than one implementation stream exists so authorship exclusion is stream-specific.",
            }, indent=2))
            return 2
        if args.pr is not None and durable_events is not None:
            excluded.update(derive(durable_events, args.pr).get("material_authors", []))
        elif args.pr is not None:
            stream = next((item for item in state.get("active_streams", []) if item.get("pr") == args.pr), None)
            if stream is None:
                print(json.dumps({
                    "status": "BLOCKED_UNKNOWN_REVIEW_STREAM",
                    "pr": args.pr,
                    "eligible": [],
                    "note": "PR-specific independent routing requires a reconciled stream when the durable ledger is disabled.",
                }, indent=2))
                return 2
            excluded.update(stream.get("material_authors", []))
        else:
            excluded.update(state.get("current_material_authors", []))

    preferences = routing_doc.get("preference_by_capability", {})
    actor_order = {actor.get("id"): index for index, actor in enumerate(actors_doc.get("actors", []))}

    eligible = []
    rejected = []
    for actor in actors_doc.get("actors", []):
        reasons: list[str] = []
        actor_id = actor["id"]
        status = readiness.get(actor_id)

        if not actor.get("enabled"):
            reasons.append("disabled")
        if not actor.get("configured"):
            reasons.append("not_configured")

        declared = set(actor.get("capabilities", []))
        missing_declared = sorted(required - declared)
        if missing_declared:
            reasons.append("missing_declared_capabilities:" + ",".join(missing_declared))

        if status is None:
            reasons.append("missing_readiness_record")
        else:
            setup_state = status.get("setup_state")
            if setup_state not in {"ready", "degraded"}:
                reasons.append(f"setup_state:{setup_state}")
            verified = set(status.get("verified_capabilities", []))
            missing_verified = sorted(required - verified)
            if missing_verified:
                reasons.append("unverified_capabilities:" + ",".join(missing_verified))
            temporarily_unavailable = required & set(status.get("temporarily_unavailable_capabilities", []))
            if temporarily_unavailable:
                reasons.append("temporarily_unavailable:" + ",".join(sorted(temporarily_unavailable)))

            access = status.get("repository_access", {})
            if required and not access.get("read"):
                reasons.append("repository_read_not_verified")
            if required & WRITE_CAPS and not access.get("write"):
                reasons.append("repository_write_not_verified")
            if (args.for_independent_gate or required & REVIEW_CAPS) and not access.get("review"):
                reasons.append("review_publish_not_verified")
            if required & MERGE_CAPS and not access.get("merge"):
                reasons.append("merge_not_verified")

            if args.unattended:
                unattended = status.get("unattended", {})
                if unattended.get("configured") is not True or unattended.get("verified") is not True:
                    reasons.append("unattended_not_verified")
                missing_dispatch = sorted(
                    capability
                    for capability in required
                    if not configured_dispatch_exists(dispatch_doc, actor_id, capability, True)
                )
                if missing_dispatch:
                    reasons.append("unattended_dispatch_missing:" + ",".join(missing_dispatch))

        if not budget_allows(actor.get("cost_class", "UNKNOWN_COST"), budget):
            reasons.append("forbidden_by_budget")

        free_implementation_slots: int | None = None
        if "implementation" in required:
            slots, availability_reasons = implementation_availability(
                actor,
                status,
                budget,
                active,
                dispatch_doc=dispatch_doc if args.unattended else None,
                require_unattended=args.unattended,
            )
            free_implementation_slots = slots
            if slots <= 0:
                reasons.extend(availability_reasons)

        if args.for_independent_gate and actor_id in excluded:
            reasons.append("material_author_conflict")
        if args.for_independent_gate and actor.get("may_independently_gate_own_material_authorship"):
            reasons.append("self_gate_policy_conflict")

        reasons = sorted(set(reasons))
        if reasons:
            rejected.append({"actor": actor_id, "reasons": reasons})
            continue

        ranks: dict[str, int] = {}
        rank_total = 0
        for capability in sorted(required):
            ordered = preferences.get(capability, [])
            try:
                rank = ordered.index(actor_id)
            except ValueError:
                rank = len(ordered) + actor_order.get(actor_id, 999)
            ranks[capability] = rank
            rank_total += rank

        eligible.append({
            "actor": actor_id,
            "preference_score": rank_total,
            "preference_ranks": ranks,
            "cost_class": actor.get("cost_class"),
            "setup_state": status.get("setup_state") if status else None,
            "free_implementation_slots": free_implementation_slots,
            "unattended": args.unattended,
        })

    eligible.sort(key=lambda item: (item["preference_score"], actor_order.get(item["actor"], 999)))
    print(json.dumps({
        "required": sorted(required),
        "pr": args.pr,
        "unattended_required": args.unattended,
        "material_authors_excluded": sorted(excluded) if args.for_independent_gate else [],
        "eligible": eligible,
        "rejected": rejected,
        "note": "Routing preference is advisory ordering after hard eligibility/capacity/dispatch filters; the first eligible actor is a proposal, not a lease.",
    }, indent=2))
    return 0 if eligible else 2


if __name__ == "__main__":
    sys.exit(main())
