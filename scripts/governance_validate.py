#!/usr/bin/env python3
"""Validate OneCompany fail-closed governance invariants."""
from __future__ import annotations

import sys

from onecompany_lib import CONTROL, load_json


def main() -> int:
    errors: list[str] = []
    try:
        governance = load_json(CONTROL / "governance.json")
        config = load_json(CONTROL / "config.json")
        actors = load_json(CONTROL / "actors.json")
        budget = load_json(CONTROL / "budget.json")
    except Exception as exc:
        print(f"ERROR: cannot load governance inputs: {exc}")
        return 1

    control = governance.get("control_plane", {})
    if control.get("human_merge_required") is not True:
        errors.append("control_plane.human_merge_required must be true")
    if control.get("fail_closed_if_diff_unavailable") is not True:
        errors.append("control_plane.fail_closed_if_diff_unavailable must be true")
    always_human = set(control.get("always_human_paths", []))
    for required in {"company/CONSTITUTION.md", ".onecompany/governance.json"}:
        if required not in always_human:
            errors.append(f"always_human_paths must contain {required}")

    policy = governance.get("policy", {})
    for key in ("no_self_escalation", "control_plane_relaxation_requires_human", "ambiguity_fails_closed"):
        if policy.get(key) is not True:
            errors.append(f"governance.policy.{key} must be true")

    supply = governance.get("supply_chain", {})
    for key in ("onecompany_managed_actions_require_sha_pin", "forbid_pull_request_target_in_managed_workflows", "forbid_write_all_in_managed_workflows"):
        if supply.get(key) is not True:
            errors.append(f"governance.supply_chain.{key} must be true")

    side = governance.get("side_effects", {})
    for key in ("require_idempotency_or_natural_deduplication", "require_rollback_or_compensation_for_destructive_actions", "require_bounded_retry_policy"):
        if side.get(key) is not True:
            errors.append(f"governance.side_effects.{key} must be true")

    safety = config.get("safety", {})
    for key in ("fail_closed_on_ambiguous_authority", "external_side_effects_require_idempotency", "destructive_change_requires_recovery_plan"):
        if safety.get(key) is not True:
            errors.append(f"config.safety.{key} must be true")
    if not isinstance(safety.get("emergency_stop"), bool):
        errors.append("config.safety.emergency_stop must be boolean")

    human_only = set(config.get("human_only_decisions", []))
    for item in {"increase_autonomy_level", "change_budget_policy", "add_or_expand_credentials", "amend_company_constitution", "relax_control_plane_guardrails"}:
        if item not in human_only:
            errors.append(f"human_only_decisions must contain {item}")

    human = next((item for item in actors.get("actors", []) if item.get("id") == "human-owner"), None)
    if not human:
        errors.append("actors.json must contain human-owner")
    elif human.get("cost_class") != "HUMAN":
        errors.append("human-owner must use HUMAN cost class")
    if "HUMAN" not in set(budget.get("cost_classes", {}).get("allowed", [])):
        errors.append("budget must classify HUMAN as allowed")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Governance validation FAILED ({len(errors)} error(s)).")
        return 1
    print("Governance validation PASS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
