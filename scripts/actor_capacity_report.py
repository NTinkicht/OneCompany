#!/usr/bin/env python3
"""Explain distinct OneCompany financial, model-runtime and lease-capacity blockers.

A read-only diagnostic: no provider calls, secret reads, leases or readiness edits.
An included subscription is not itself proof of a cloud coding/review worker.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from capacity_lib import implementation_availability
from onecompany_lib import CONTROL, budget_allows, load_json

FAILURE_KIND = {
    "TOKEN_BUDGET_EXCEEDED": "MODEL_EXECUTION_TOKEN_CEILING",
    "TURN_LIMIT_EXCEEDED": "MODEL_EXECUTION_TURN_CEILING",
    "WAKE_TIMEOUT": "MODEL_EXECUTION_TIMEOUT",
    "CAPACITY_DEGRADED": "PROVIDER_QUOTA_OR_RATE_LIMIT_UNVERIFIED",
    "PROVIDER_QUOTA_EXHAUSTED": "PROVIDER_QUOTA_OR_RATE_LIMIT",
    "BUDGET_BLOCKED": "FINANCIAL_POLICY_BLOCKED",
    "CONFIG_BLOCKED": "PROVIDER_CONFIGURATION_BLOCKED",
    "AUTH_BLOCKED": "PROVIDER_AUTHENTICATION_BLOCKED",
    "ENTITLEMENT_BLOCKED": "PROVIDER_ENTITLEMENT_BLOCKED",
    "REVIEW_TARGET_BLOCKED": "EXACT_HEAD_REVIEW_PRECONDITION_BLOCKED",
}


def classify_failure(status: str | None) -> str:
    """Do not conflate total agent token ceiling with subscription exhaustion."""
    if status is None:
        return "NOT_PROBED"
    return FAILURE_KIND.get(status, "UNCLASSIFIED_RUNTIME_STATUS")


def find_actor(items: dict[str, Any], actor_id: str, *, key: str) -> dict | None:
    """Return the uniquely identified actor, failing closed on duplicates."""
    matches = [item for item in items.get("actors", []) if item.get(key) == actor_id]
    if len(matches) > 1:
        raise ValueError("DUPLICATE_ACTOR_REGISTRY_ENTRY")
    return matches[0] if matches else None


def diagnose(
    actor_id: str,
    capability: str,
    actors: dict[str, Any],
    readiness: dict[str, Any],
    dispatch: dict[str, Any],
    budget: dict[str, Any],
    *,
    runtime_status: str | None = None,
    unattended: bool = True,
) -> dict[str, Any]:
    """Report capability-specific facts without fabricating a provider quota probe."""
    actor = find_actor(actors, actor_id, key="id")
    ready = find_actor(readiness, actor_id, key="actor_id")
    entry = find_actor(dispatch, actor_id, key="actor_id")
    cost_class = actor.get("cost_class", "UNKNOWN_COST") if actor else "UNKNOWN_COST"
    ai = budget.get("ai", {})
    zero_spend = (
        ai.get("additional_monthly_spend_cap") == 0
        and all(ai.get(field) is False for field in (
            "allow_paid_fallback", "allow_overage", "allow_auto_topup",
            "allow_new_paid_vendor",
        ))
        and ai.get("unknown_cost_behavior") == "forbid"
    )
    financial_allowed = bool(actor) and zero_spend and budget_allows(cost_class, budget)
    mechanisms = [
        m.get("id")
        for m in (entry or {}).get("mechanisms", [])
        if m.get("configured") is True
        and capability in m.get("capabilities", [])
        and (not unattended or m.get("unattended") is True)
    ]
    reasons: list[str] = []
    if actor is None:
        reasons.append("unknown_actor")
    elif actor.get("enabled") is not True or actor.get("configured") is not True:
        reasons.append("actor_not_enabled_and_configured")
    if ready is None:
        reasons.append("missing_readiness")
    else:
        if ready.get("setup_state") not in ("ready", "degraded"):
            reasons.append("actor_not_ready")
        if capability not in ready.get("verified_capabilities", []):
            reasons.append("capability_not_verified")
        if capability in ready.get("temporarily_unavailable_capabilities", []):
            reasons.append("capability_temporarily_unavailable")
        if unattended and (
            ready.get("unattended", {}).get("configured") is not True
            or ready.get("unattended", {}).get("verified") is not True
        ):
            reasons.append("unattended_not_verified")
        if capability in ("implementation", "code_review"):
            required_access = "write" if capability == "implementation" else "review"
            if ready.get("repository_access", {}).get(required_access) is not True:
                reasons.append(f"repository_{required_access}_not_verified")
    if not mechanisms:
        reasons.append("no_configured_execution_mechanism")
    if not financial_allowed:
        reasons.append("financial_policy_blocked")
    measured_slots = 0
    if capability == "implementation" and actor and ready:
        measured_slots, capacity_reasons = implementation_availability(
            actor, ready, budget, [], dispatch_doc=dispatch,
            require_unattended=unattended,
        )
        reasons.extend(capacity_reasons)
    return {
        "actor": actor_id,
        "capability": capability,
        "financial_policy": (
            "ALLOWED_NO_ADDITIONAL_SPEND" if financial_allowed
            else "FINANCIAL_POLICY_BLOCKED"
        ),
        "cost_class": cost_class,
        "provider_quota": "NOT_PROBED_BY_LEASE",
        "model_token_ceiling": "NOT_PROBED_BY_LEASE",
        "observed_runtime_failure": classify_failure(runtime_status),
        "implementation_free_slots": measured_slots if capability == "implementation" else None,
        "configured_mechanisms": mechanisms,
        "admission": "NOT_QUALIFIED" if reasons else "ELIGIBLE_FOR_FURTHER_LEASE_CHECKS",
        "reasons": sorted(set(reasons)),
    }


def main() -> int:
    """Read only repository policy; never infer balance from a Codespace session."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--capability", choices=("implementation", "code_review"),
                        required=True)
    parser.add_argument("--runtime-status", choices=tuple(FAILURE_KIND))
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()
    try:
        result = diagnose(
            args.actor, args.capability,
            load_json(CONTROL / "actors.json"),
            load_json(CONTROL / "readiness.json"),
            load_json(CONTROL / "dispatch.json"),
            load_json(CONTROL / "budget.json"),
            runtime_status=args.runtime_status,
            unattended=not args.interactive,
        )
    except (ValueError, KeyError, OSError, TypeError, json.JSONDecodeError):
        print(json.dumps({"status": "CAPACITY_DIAGNOSTIC_UNAVAILABLE"}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["admission"] == "ELIGIBLE_FOR_FURTHER_LEASE_CHECKS" else 2


if __name__ == "__main__":
    sys.exit(main())
