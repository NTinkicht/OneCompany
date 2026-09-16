#!/usr/bin/env python3
"""Validate the B2 staged handoff activation boundary."""
from __future__ import annotations

import sys

import handoff


def main() -> int:
    try:
        policy = handoff.load_policy()
        errors: list[str] = []
        activation = policy.get("activation") or {}
        safety = policy.get("safety") or {}
        publisher = policy.get("publisher_policy") or {}

        if policy.get("enabled") is not False:
            errors.append("B2 staged integration must remain disabled")
        if policy.get("mode") != "staged_only":
            errors.append("B2 integration mode must remain staged_only")
        if activation.get("b1_protected_main_proven") is not False:
            errors.append("B1 protected-main proof cannot be predeclared on integration")
        if activation.get("ledger_replay_proven") is not False:
            errors.append("protected-main ledger replay cannot be predeclared on integration")
        if activation.get("evidence_refs") != []:
            errors.append("activation evidence must remain empty before protected-main proof")
        if publisher.get("automation_publishers") != {}:
            errors.append("no automation publisher may be trusted before separate activation review")
        required = {
            "events_are_wake_hints_only": True,
            "must_reconcile_authoritative_state": True,
            "hint_payload_can_create_authority": False,
            "proposal_only_until_activation": True,
            "never_create_duplicate_writer": True,
            "emergency_stop_is_sovereign": True,
            "human_code_owner_remains_human": True,
            "zero_extra_spend_required": True,
            "pull_request_target_forbidden": True,
            "candidate_cache_is_authority": False,
        }
        for key, expected in required.items():
            if safety.get(key) != expected:
                errors.append(f"handoff safety invariant mismatch:{key}")
        if handoff.activation_ready(policy):
            errors.append("staged integration policy must not be activation-ready")
        if errors:
            print("B2 handoff validation FAIL:")
            for error in errors:
                print(f"- {error}")
            return 1
        print("B2 handoff validation PASS (staged, proposal-only, no automation publisher).")
        return 0
    except Exception as exc:
        print(f"B2 handoff validation FAIL: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
