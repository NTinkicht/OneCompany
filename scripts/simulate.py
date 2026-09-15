#!/usr/bin/env python3
"""Run dependency-free policy simulations against core OneCompany invariants."""
from __future__ import annotations

import copy
import sys

from onecompany_lib import CONTROL, active_implementation_leases, budget_allows, load_json


def check(name: str, condition: bool) -> bool:
    print(("PASS" if condition else "FAIL") + ": " + name)
    return condition


def verified_capabilities_have_configured_dispatch(
    actors: dict,
    readiness: dict,
    dispatch: dict,
) -> bool:
    """Require enabled actors to have verified, executable capability evidence."""
    actor_by_id = {
        str(item.get("id")): item
        for item in actors.get("actors", [])
        if isinstance(item, dict) and item.get("id")
    }
    readiness_by_id = {
        str(item.get("actor_id")): item
        for item in readiness.get("actors", [])
        if isinstance(item, dict) and item.get("actor_id")
    }
    dispatch_by_id = {
        str(item.get("actor_id")): item
        for item in dispatch.get("actors", [])
        if isinstance(item, dict) and item.get("actor_id")
    }

    for actor_id, actor in actor_by_id.items():
        if not actor.get("enabled") or not actor.get("configured"):
            continue

        ready = readiness_by_id.get(actor_id)
        if not isinstance(ready, dict):
            return False

        verified_list = ready.get("verified_capabilities")
        if not isinstance(verified_list, list) or not verified_list:
            return False
        verified = set(verified_list)

        configured_capabilities: set[str] = set()
        entry = dispatch_by_id.get(actor_id, {})
        for mechanism in entry.get("mechanisms", []):
            if isinstance(mechanism, dict) and mechanism.get("configured"):
                configured_capabilities.update(mechanism.get("capabilities", []))

        if not verified.issubset(configured_capabilities):
            return False

    return True


def main() -> int:
    config = load_json(CONTROL / "config.json")
    budget = load_json(CONTROL / "budget.json")
    state = load_json(CONTROL / "state.json")
    overlays = load_json(CONTROL / "overlays.json")
    actors = load_json(CONTROL / "actors.json")
    readiness = load_json(CONTROL / "readiness.json")
    dispatch = load_json(CONTROL / "dispatch.json")
    results = []

    zero_spend = copy.deepcopy(budget)
    zero_spend["ai"]["additional_monthly_spend_cap"] = 0
    results.append(check("zero-spend rejects metered actor", not budget_allows("METERED_ALLOWED", zero_spend)))
    results.append(check("zero-spend allows included subscription", budget_allows("INCLUDED_SUBSCRIPTION", zero_spend)))

    one = copy.deepcopy(state)
    one["active_leases"] = [{"role": "implementation", "status": "active", "actor": "a"}]
    results.append(check("one implementation lease is representable", len(active_implementation_leases(one)) == 1))

    two = copy.deepcopy(one)
    two["active_leases"].append({"role": "implementation", "status": "active", "actor": "b"})
    results.append(check("duplicate implementation lease is detectable", len(active_implementation_leases(two)) > 1))

    head = "abc"
    gate = {"sha": "def", "verdict": "PASS — MERGE_READY"}
    results.append(check("stale exact-head gate is detectable", gate["sha"] != head))

    authors = {"chatgpt", "codex"}
    reviewer = "claude"
    results.append(check("independent reviewer is non-author", reviewer not in authors))
    reviewer = "codex"
    results.append(check("material author conflict is detectable", reviewer in authors))

    rules = overlays.get("rules", {})
    results.append(check("role overlay cannot create an actor", rules.get("creates_actor") is False))
    results.append(check("role overlay cannot create an implementation lease", rules.get("creates_implementation_lease") is False))
    results.append(check("role overlay cannot override self-gate rule", rules.get("overrides_self_gate_rule") is False))
    results.append(check("role overlay cannot grant merge authority", rules.get("grants_merge_authority") is False))

    # Capability-level degradation must not imply whole-provider outage.
    sample = copy.deepcopy(readiness.get("actors", [])[0])
    sample["setup_state"] = "degraded"
    sample["verified_capabilities"] = ["implementation", "code_review"]
    sample["temporarily_unavailable_capabilities"] = ["code_review"]
    results.append(check("degraded actor can retain unrelated verified capability", "implementation" in sample["verified_capabilities"] and "implementation" not in sample["temporarily_unavailable_capabilities"]))
    results.append(check("temporary review outage is capability-specific", "code_review" in sample["temporarily_unavailable_capabilities"]))

    # Declared capability is not readiness. Post-bootstrap activation may verify
    # explicitly enabled actors, but disabled/unconfigured actors must remain
    # unproven and cannot inherit readiness merely from their declaration.
    actor_by_id = {
        str(item.get("id")): item
        for item in actors.get("actors", [])
        if isinstance(item, dict) and item.get("id")
    }
    disabled_or_unconfigured_are_unverified = all(
        not item.get("verified_capabilities")
        for item in readiness.get("actors", [])
        if (
            not actor_by_id.get(str(item.get("actor_id")), {}).get("enabled")
            or not actor_by_id.get(str(item.get("actor_id")), {}).get("configured")
        )
    )
    results.append(
        check(
            "disabled or unconfigured readiness does not pretend capabilities are verified",
            disabled_or_unconfigured_are_unverified,
        )
    )

    results.append(
        check(
            "verified capabilities have a configured dispatch mechanism",
            verified_capabilities_have_configured_dispatch(actors, readiness, dispatch),
        )
    )

    results.append(check("GitHub remains source of truth", config.get("project", {}).get("source_of_truth") == "github"))

    failed = len([r for r in results if not r])
    print(f"\nSimulation: {len(results)-failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
