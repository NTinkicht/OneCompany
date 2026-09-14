#!/usr/bin/env python3
"""Validate OneCompany durable-ledger runtime configuration."""
from __future__ import annotations

import sys

from onecompany_lib import CONTROL, autonomy_number, load_json

REQUIRED_EVENTS = {
    "ROLE_LEASE_ASSIGNED",
    "ROLE_LEASE_RELEASED",
    "ROLE_LEASE_TRANSFERRED",
    "ROLE_LEASE_RENEWED",
    "ROLE_LEASE_REAPED",
    "GATE",
    "MERGED",
}


def main() -> int:
    ledger = load_json(CONTROL / "ledger.json")
    config = load_json(CONTROL / "config.json")
    supervision = load_json(CONTROL / "supervision.json")
    errors: list[str] = []
    warnings: list[str] = []

    accepted = ledger.get("accepted_event_types", [])
    if len(accepted) != len(set(accepted)):
        errors.append("ledger.accepted_event_types must be unique")
    missing = sorted(REQUIRED_EVENTS - set(accepted))
    if missing:
        errors.append(f"ledger is missing required event types: {missing}")

    lifecycle = ledger.get("lease_lifecycle", {})
    ttl = lifecycle.get("ttl_seconds")
    if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0:
        errors.append("ledger.lease_lifecycle.ttl_seconds must be a positive integer")
    if lifecycle.get("renewal_progress_kinds") != ["pr_head"]:
        errors.append("ledger.lease_lifecycle.renewal_progress_kinds must be ['pr_head']")
    if lifecycle.get("implicit_expiry_revokes_authority") is not True:
        errors.append("ledger lease expiry must revoke implementation authority")

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

    if (
        ledger.get("required_for_autonomous_merge")
        and level >= 3
        and not ledger.get("enabled")
    ):
        errors.append(
            "L3+ autonomous delivery requires the durable ledger enabled for binding gates/leases"
        )
    if (
        ledger.get("required_for_continuous_autonomy")
        and level >= 4
        and not ledger.get("enabled")
    ):
        errors.append("L4/L5 continuous autonomy requires the durable ledger enabled")
    if (
        supervision.get("enabled")
        and supervision.get("mode") == "orchestrate"
        and not ledger.get("enabled")
    ):
        errors.append("orchestrating scheduled supervision requires the durable ledger enabled")

    team_room = supervision.get("coordination", {}).get("team_room_issue_number")
    if ledger.get("enabled") and team_room not in {None, ledger.get("issue_number")}:
        warnings.append(
            "supervision Team Room issue differs from durable ledger issue; verify this split is intentional"
        )

    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(
            f"OneCompany ledger validation FAILED ({len(errors)} error(s), "
            f"{len(warnings)} warning(s))."
        )
        return 1
    print(f"OneCompany ledger validation PASS ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
