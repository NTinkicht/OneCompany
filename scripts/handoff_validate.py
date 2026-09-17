#!/usr/bin/env python3
"""Validate the active B2 event-driven handoff boundary."""
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
        runtime = policy.get("runtime") or {}

        if policy.get("enabled") is not True:
            errors.append("B2 handoffs must be enabled")
        if policy.get("mode") != "active":
            errors.append("B2 handoff mode must be active")
        if activation.get("b1_protected_main_proven") is not True:
            errors.append("B1 protected-main proof is required")
        if activation.get("ledger_replay_proven") is not True:
            errors.append("protected-main ledger replay proof is required")
        refs = activation.get("evidence_refs")
        if not isinstance(refs, list) or len(refs) < 3:
            errors.append("activation requires protected-main and workflow evidence refs")
        if not handoff.activation_ready(policy):
            errors.append("active B2 policy is not activation-ready")
        if publisher.get("publisher_identity_and_event_type_both_required") is not True:
            errors.append("publisher identity and event type must both be enforced")
        mapping = publisher.get("automation_publishers")
        if not isinstance(mapping, dict):
            errors.append("automation_publishers must be an object")
        elif any(not isinstance(v, list) or not v for v in mapping.values()):
            errors.append("every trusted automation publisher requires scoped event types")

        required_runtime = {
            "event_reconciliation_enabled": True,
            "current_autonomy_level": "L1",
            "l1_behavior": "reconcile_and_notify_only",
            "mutation_requires_preexisting_authority": True,
            "read_only_unattended_dispatch_allowed": True,
            "write_dispatch_requires_canonical_lease": True,
            "automatic_failover_allowed": False,
            "automatic_merge_allowed": False,
        }
        for key, expected in required_runtime.items():
            if runtime.get(key) != expected:
                errors.append(f"handoff runtime invariant mismatch:{key}")

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
        if errors:
            print("B2 handoff validation FAIL:")
            for error in errors:
                print(f"- {error}")
            return 1
        print("B2 handoff validation PASS (active reconciliation, L1 notify-only mutation boundary).")
        return 0
    except Exception as exc:
        print(f"B2 handoff validation FAIL: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
