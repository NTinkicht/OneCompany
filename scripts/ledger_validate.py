#!/usr/bin/env python3
"""Validate OneCompany durable-ledger policy."""
from __future__ import annotations

import sys

from onecompany_lib import CONTROL, autonomy_number, load_json


def main() -> int:
    ledger = load_json(CONTROL / "ledger.json")
    config = load_json(CONTROL / "config.json")
    supervision = load_json(CONTROL / "supervision.json")
    errors: list[str] = []
    warnings: list[str] = []

    accepted = ledger.get("accepted_event_types", [])
    if len(accepted) != len(set(accepted)):
        errors.append("ledger.accepted_event_types must be unique")
    for required in ("ROLE_LEASE_ASSIGNED", "ROLE_LEASE_RELEASED", "GATE"):
        if required not in accepted:
            errors.append(f"ledger must accept {required}")

    policy = ledger.get("policy", {})
    for key in ("github_issue_comments_are_durable_coordination_record", "local_state_is_cache", "ignore_untrusted_publishers", "binding_gate_must_be_durable", "continuous_supervisors_must_share_ledger"):
        if policy.get(key) is not True:
            errors.append(f"ledger.policy.{key} must be true")

    if ledger.get("enabled"):
        if not isinstance(ledger.get("issue_number"), int) or ledger.get("issue_number") <= 0:
            errors.append("enabled ledger requires a positive issue_number")
        if not ledger.get("trusted_publisher_logins"):
            errors.append("enabled ledger requires trusted_publisher_logins")

    try:
        level = autonomy_number(config.get("autonomy", {}).get("level", "L0"))
    except ValueError as exc:
        errors.append(str(exc))
        level = 0

    if ledger.get("required_for_continuous_autonomy") and level >= 4 and not ledger.get("enabled"):
        errors.append("L4/L5 continuous autonomy requires the durable ledger enabled")
    if supervision.get("enabled") and supervision.get("mode") == "orchestrate" and not ledger.get("enabled"):
        errors.append("orchestrating scheduled supervision requires the durable ledger enabled")

    if ledger.get("enabled") and supervision.get("coordination", {}).get("team_room_issue_number") not in {None, ledger.get("issue_number")}:
        warnings.append("supervision Team Room issue differs from durable ledger issue; verify this split is intentional")

    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"OneCompany ledger validation FAILED ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1
    print(f"OneCompany ledger validation PASS ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
