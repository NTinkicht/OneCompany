#!/usr/bin/env python3
"""Choose eligible actors after capability, readiness, budget, capacity, dispatch and authorship filters."""
from __future__ import annotations

import argparse
import json
import sys

from capacity_lib import configured_dispatch_exists, implementation_availability
from execution_core import WorkerProfile, WorkerTier, rank_worker_profiles
from lease_lifecycle import coordination_view
from onecompany_lib import CONTROL, load_json

WRITE_CAPS = {"implementation", "ci_remediation"}
REVIEW_CAPS = {"code_review", "security_review"}
MERGE_CAPS = {"merge_execution"}
FAILOVER_TRIGGERS = {
    "quota_exhausted",
    "capacity_exhausted",
    "runtime_unavailable",
    "environment_unavailable",
    "permission_failure",
    "no_progress_after_reconcile",
    "repeated_failed_remediation",
    "security_concern",
    "human_override",
}


def dispatch_gaps(
    dispatch_doc: dict,
    actor_id: str,
    required: set[str],
    unattended: bool,
) -> list[str]:
    """Return requested capabilities that lack a configured execution mechanism."""
    return sorted(
        capability
        for capability in required
        if not configured_dispatch_exists(
            dispatch_doc,
            actor_id,
            capability,
            unattended,
        )
    )


def zero_spend_budget_allows(cost_class: str, budget: dict) -> bool:
    """Allow only cost classes explicitly approved for the zero-extra-spend router."""
    return cost_class in set(budget.get("cost_classes", {}).get("allowed", []))


def execution_profile_order(
    role: str | None,
    complexity: str | None,
    budget: dict,
) -> dict[str, int]:
    """Return an optional advisory actor order after hard router eligibility.

    Execution metadata never creates eligibility. Callers must supply both role and
    complexity or neither so an incomplete hint cannot silently affect routing.
    """
    if role is None and complexity is None:
        return {}
    if not role or not complexity:
        raise ValueError("--execution-role and --complexity must be supplied together")
    profile_doc = load_json(CONTROL / "execution-profiles.json")
    profiles = [WorkerProfile.from_dict(item) for item in profile_doc.get("profiles", [])]
    ranked = rank_worker_profiles(
        profiles,
        role=role,
        complexity=WorkerTier(complexity),
        allowed_cost_classes=set(budget.get("cost_classes", {}).get("allowed", [])),
    )
    return {profile.actor_id: index for index, profile in enumerate(ranked)}


def failover_context(
    active: list[dict],
    replace_lease_id: str | None,
    trigger: str | None,
    required: set[str],
) -> tuple[dict | None, list[str]]:
    """Validate an explicit failover proposal without mutating lease authority."""
    if replace_lease_id is None and trigger is None:
        return None, []
    reasons: list[str] = []
    if "implementation" not in required:
        reasons.append("failover_requires_implementation_capability")
    if not replace_lease_id:
        reasons.append("failover_source_lease_required")
    if not trigger:
        reasons.append("failover_trigger_required")
    elif trigger not in FAILOVER_TRIGGERS:
        reasons.append("failover_trigger_not_allowed")

    source = None
    if replace_lease_id:
        source = next(
            (item for item in active if item.get("id") == replace_lease_id),
            None,
        )
        if source is None:
            reasons.append("failover_source_lease_not_active")
    return source, sorted(set(reasons))


def main() -> int:
    """Resolve a deterministic route proposal; never create or transfer authority."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", action="append", required=True, help="Required capability; repeatable")
    parser.add_argument("--exclude-author", action="append", default=[], help="Additional actor ID materially conflicted for independent gate")
    parser.add_argument("--for-independent-gate", action="store_true")
    parser.add_argument("--pr", type=int, help="PR whose authorship should be excluded for independent review")
    parser.add_argument("--unattended", action="store_true", help="Require a verified configured unattended execution path")
    parser.add_argument("--replace-lease-id", help="Canonical active implementation lease being considered for failover")
    parser.add_argument("--failover-trigger", help="Explicit allowlisted reason for a same-stream failover proposal")
    parser.add_argument("--execution-role", help="Optional execution role used only to rank actors that already passed hard eligibility")
    parser.add_argument("--complexity", choices=[item.value for item in WorkerTier], help="Optional execution complexity; requires --execution-role")
    args = parser.parse_args()

    actors_doc = load_json(CONTROL / "actors.json")
    readiness_doc = load_json(CONTROL / "readiness.json")
    routing_doc = load_json(CONTROL / "routing.json")
    dispatch_doc = load_json(CONTROL / "dispatch.json")
    budget = load_json(CONTROL / "budget.json")
    readiness = {item.get("actor_id"): item for item in readiness_doc.get("actors", [])}
    required = set(args.capability)

    try:
        profile_order = execution_profile_order(args.execution_role, args.complexity, budget)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({
            "status": "BLOCKED_INVALID_EXECUTION_PROFILE_REQUEST",
            "error": str(exc),
            "eligible": [],
        }, indent=2))
        return 2

    try:
        global_view = coordination_view()
        active = [
            item
            for item in global_view.get("active_leases", [])
            if item.get("role") == "implementation"
        ]
    except Exception as exc:
        print(json.dumps({
            "status": "BLOCKED_COORDINATION_UNAVAILABLE",
            "error": str(exc),
            "eligible": [],
            "note": "Routing fails closed when coordination truth cannot be reconstructed.",
        }, indent=2))
        return 2

    source_lease, failover_reasons = failover_context(
        active,
        args.replace_lease_id,
        args.failover_trigger,
        required,
    )
    if failover_reasons:
        print(json.dumps({
            "status": "BLOCKED_FAILOVER_NOT_AUTHORIZED",
            "eligible": [],
            "reasons": failover_reasons,
            "note": "A route proposal cannot create failover authority. Timer/heartbeat-only failover is not accepted.",
        }, indent=2))
        return 2

    excluded = set(args.exclude_author)
    if args.for_independent_gate:
        if args.pr is not None:
            try:
                excluded.update(coordination_view(args.pr).get("material_authors", []))
            except Exception as exc:
                print(json.dumps({
                    "status": "BLOCKED_COORDINATION_UNAVAILABLE",
                    "error": str(exc),
                    "eligible": [],
                }, indent=2))
                return 2
        elif len(active) > 1:
            print(json.dumps({
                "status": "BLOCKED_AMBIGUOUS_REVIEW_STREAM",
                "eligible": [],
                "note": "Pass --pr when more than one implementation stream exists so authorship exclusion is stream-specific.",
            }, indent=2))
            return 2
        else:
            excluded.update(global_view.get("material_authors", []))

    preferences = routing_doc.get("preference_by_capability", {})
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

        missing_dispatch = dispatch_gaps(
            dispatch_doc,
            actor_id,
            required,
            args.unattended,
        )
        if missing_dispatch:
            prefix = "unattended_dispatch_missing:" if args.unattended else "dispatch_missing:"
            reasons.append(prefix + ",".join(missing_dispatch))

        if not zero_spend_budget_allows(actor.get("cost_class", "UNKNOWN_COST"), budget):
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
                exclude_lease_id=(
                    str(source_lease.get("id"))
                    if source_lease is not None
                    else None
                ),
            )
            free_implementation_slots = slots
            if slots <= 0:
                reasons.extend(availability_reasons)
            if source_lease is not None and actor_id == source_lease.get("actor"):
                reasons.append("failover_source_actor")

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
                rank = len(ordered) + 1000
            ranks[capability] = rank
            rank_total += rank

        eligible.append({
            "actor": actor_id,
            "preference_score": rank_total,
            "preference_ranks": ranks,
            "execution_profile_rank": profile_order.get(actor_id) if profile_order else None,
            "cost_class": actor.get("cost_class"),
            "setup_state": status.get("setup_state") if status else None,
            "free_implementation_slots": free_implementation_slots,
            "unattended": args.unattended,
        })

    if profile_order:
        eligible.sort(key=lambda item: (
            item["execution_profile_rank"] if item["execution_profile_rank"] is not None else len(profile_order) + 1000,
            item["preference_score"],
            item["actor"],
        ))
    else:
        eligible.sort(key=lambda item: (item["preference_score"], item["actor"]))
    payload = {
        "status": "ROUTE_READY" if eligible else "BLOCKED_NO_ELIGIBLE_ROUTE",
        "required": sorted(required),
        "pr": args.pr,
        "unattended_required": args.unattended,
        "execution_role": args.execution_role,
        "complexity": args.complexity,
        "material_authors_excluded": sorted(excluded) if args.for_independent_gate else [],
        "proposed_actor": eligible[0]["actor"] if eligible else None,
        "eligible": eligible,
        "rejected": rejected,
        "failover": (
            {
                "source_lease_id": source_lease.get("id"),
                "source_actor": source_lease.get("actor"),
                "trigger": args.failover_trigger,
                "requires_atomic_lease_transfer": True,
            }
            if source_lease is not None
            else None
        ),
        "note": "Routing is a deterministic proposal after hard eligibility, zero-spend, capacity, dispatch and authorship filters. Optional execution-profile metadata only ranks actors that already passed those controls; routing never creates or transfers a lease.",
    }
    print(json.dumps(payload, indent=2))
    return 0 if eligible else 2


if __name__ == "__main__":
    sys.exit(main())
