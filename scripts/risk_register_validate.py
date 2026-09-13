#!/usr/bin/env python3
"""Validate planning risk-register semantics beyond JSON shape."""
from __future__ import annotations

import sys
from typing import Any

from onecompany_lib import CONTROL, load_json


def validate_risks(risks: list[dict[str, Any]], policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    domains = set(policy.get("domains", []))
    gates = policy.get("gates", {})
    seen: set[str] = set()

    for risk in risks:
        risk_id = str(risk.get("id") or "<missing-risk-id>")
        if risk_id in seen:
            errors.append(f"{risk_id}: duplicate risk id")
        seen.add(risk_id)

        if risk.get("domain") not in domains:
            errors.append(f"{risk_id}: unknown risk domain {risk.get('domain')!r}")

        try:
            inherent = int(risk.get("likelihood")) * int(risk.get("impact"))
            residual = int(risk.get("residual_likelihood")) * int(risk.get("residual_impact"))
        except (TypeError, ValueError):
            errors.append(f"{risk_id}: likelihood/impact values must be integers")
            continue

        if risk.get("inherent_score") != inherent:
            errors.append(f"{risk_id}: inherent_score must equal likelihood*impact ({inherent})")
        if risk.get("residual_score") != residual:
            errors.append(f"{risk_id}: residual_score must equal residual_likelihood*residual_impact ({residual})")

        owner = str(risk.get("owner") or "").strip()
        if risk.get("status") == "open" and gates.get("unowned_open_risk_blocks_ready", True) and not owner:
            errors.append(f"{risk_id}: open risk requires a named owner")
        if residual >= 10 and gates.get("high_residual_risk_requires_named_owner", True) and not owner:
            errors.append(f"{risk_id}: high/critical residual risk requires a named owner")

        treatment = risk.get("treatment")
        mitigations = risk.get("mitigations") or []
        if treatment == "reduce" and not mitigations:
            errors.append(f"{risk_id}: reduce treatment requires at least one mitigation")

        acceptance = risk.get("acceptance")
        accepted_by = acceptance.get("approved_by") if isinstance(acceptance, dict) else None
        human_accepted = bool(isinstance(acceptance, dict) and acceptance.get("human") is True and accepted_by)

        # A critical residual risk remains critical regardless of the treatment label.
        # Proceeding with it therefore requires an explicit human acceptance record.
        if residual >= 17 and gates.get("critical_residual_risk_requires_human_acceptance", True) and not human_accepted:
            errors.append(f"{risk_id}: critical residual risk requires explicit human acceptance")

        # Explicit acceptance of high/critical residual risk must name its authority.
        if treatment == "accept" and residual >= 10 and not human_accepted:
            errors.append(f"{risk_id}: accepting high/critical residual risk requires explicit human acceptance authority")

        # Security/privacy/safety risks can never disappear through a bare `accept` label.
        if treatment == "accept" and risk.get("domain") in {"security", "privacy", "safety"} and not human_accepted:
            errors.append(f"{risk_id}: {risk.get('domain')} risk cannot be silently accepted")

        if risk.get("status") == "accepted" and not human_accepted:
            errors.append(f"{risk_id}: status=accepted requires an explicit human acceptance record")

    return errors


def main() -> int:
    register = load_json(CONTROL / "risk-register.json")
    policy = load_json(CONTROL / "risk.json")
    errors = validate_risks(register.get("risks", []), policy)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Risk-register validation FAILED ({len(errors)} error(s)).")
        return 1
    print("Risk-register validation PASS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
