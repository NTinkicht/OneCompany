#!/usr/bin/env python3
"""Validate that routing candidates have explicit execution/wake mechanisms."""
from __future__ import annotations

import sys

from onecompany_lib import CONTROL, load_json


def main() -> int:
    actors_doc = load_json(CONTROL / "actors.json")
    readiness_doc = load_json(CONTROL / "readiness.json")
    dispatch = load_json(CONTROL / "dispatch.json")
    errors: list[str] = []
    warnings: list[str] = []

    actor_caps = {item["id"]: set(item.get("capabilities", [])) for item in actors_doc.get("actors", []) if item.get("id")}
    readiness = {item["actor_id"]: item for item in readiness_doc.get("actors", []) if item.get("actor_id")}
    dispatch_by_actor: dict[str, dict] = {}

    policy = dispatch.get("policy", {})
    for key in ("routing_does_not_equal_execution", "no_dispatch_without_verified_capability", "unattended_supervisor_requires_unattended_dispatch", "dispatch_never_creates_authority"):
        if policy.get(key) is not True:
            errors.append(f"dispatch.policy.{key} must be true")
    if policy.get("missing_execution_path_behavior") != "CAPACITY_BLOCKED":
        errors.append("dispatch.policy.missing_execution_path_behavior must be CAPACITY_BLOCKED")

    for entry in dispatch.get("actors", []):
        actor_id = entry.get("actor_id")
        if not actor_id:
            errors.append("dispatch actor missing actor_id")
            continue
        if actor_id in dispatch_by_actor:
            errors.append(f"duplicate dispatch actor: {actor_id}")
            continue
        dispatch_by_actor[actor_id] = entry
        if actor_id not in actor_caps:
            errors.append(f"dispatch references unknown actor: {actor_id}")
            continue
        mechanism_ids: set[str] = set()
        for mechanism in entry.get("mechanisms", []):
            mid = mechanism.get("id")
            if not mid:
                errors.append(f"dispatch {actor_id} has mechanism without id")
                continue
            if mid in mechanism_ids:
                errors.append(f"dispatch {actor_id} duplicate mechanism id: {mid}")
            mechanism_ids.add(mid)
            caps = set(mechanism.get("capabilities", []))
            undeclared = caps - actor_caps[actor_id]
            if undeclared:
                errors.append(f"dispatch {actor_id}/{mid} exposes undeclared capabilities: {sorted(undeclared)}")
            if mechanism.get("configured") and not mechanism.get("evidence"):
                warnings.append(f"configured dispatch {actor_id}/{mid} has no evidence reference")
            if mechanism.get("configured") and mechanism.get("unattended"):
                actor_ready = readiness.get(actor_id, {})
                unattended = actor_ready.get("unattended", {})
                if unattended.get("configured") is not True or unattended.get("verified") is not True:
                    errors.append(f"configured unattended dispatch {actor_id}/{mid} requires readiness unattended configured+verified")

    missing = set(actor_caps) - set(dispatch_by_actor)
    if missing:
        errors.append(f"actors missing dispatch records: {sorted(missing)}")

    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"OneCompany dispatch validation FAILED ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1
    print(f"OneCompany dispatch validation PASS ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
