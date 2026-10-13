#!/usr/bin/env python3
"""Pure, fail-closed merge authority lane for the *trusted PR base* policy.

Classification NEVER substitutes for exact-head CI, independent approval,
provenance, required check sources, active leases or expected-head merges.
"""
from __future__ import annotations

from onecompany_lib import path_matches_any

ROUTINE = "ROUTINE_REVIEWED"
PROTECTED = "PROTECTED_REVIEWED"
OWNER = "OWNER_GOVERNED"

# Extra defense-in-depth: a candidate may not silently unclassify a trusted
# reviewer/merge authority path by editing candidate-controlled policy.
MINIMUM_OWNER_PATHS = frozenset({
    ".onecompany/governance.json",
    ".onecompany/config.json",
    ".onecompany/required-checks.json",
    ".onecompany/identity.json",
    ".onecompany/actors.json",
    ".onecompany/readiness.json",
    ".onecompany/dispatch.json",
    ".onecompany/budget.json",
    "scripts/merge.py",
    "scripts/merge_lane.py",
    "scripts/review_authorization.py",
    "scripts/platform_identity.py",
    "scripts/github_controls.py",
    "scripts/trusted_assurance.py",
    "scripts/required_checks.py",
    "scripts/scope_guard.py",
    "scripts/mistral_external_dispatch.py",
    "scripts/mistral_external_review.py",
    ".github/mistral_external_review_impl.py",
})


def classify_merge_lane(paths: list[str], policy: dict) -> dict:
    if (
        not isinstance(paths, list) or not paths
        or not isinstance(policy, dict)
        or not isinstance(policy.get("protected_paths"), list)
        or not isinstance(policy.get("always_human_paths"), list)
        or not isinstance(policy.get("human_merge_required"), bool)
    ):
        raise ValueError("MERGE_LANE_INPUT_OR_POLICY_INVALID")

    guarded: set[str] = set()
    owner_paths: set[str] = set()
    for item in paths:
        if (
            not isinstance(item, str) or not item
            or item.startswith("/") or "\\" in item
            or ".." in item.split("/")
            or "//" in item or item.startswith("./")
        ):
            raise ValueError("MERGE_LANE_PATH_UNSAFE")
        if path_matches_any(item, policy["protected_paths"]):
            guarded.add(item)
        if (
            item in MINIMUM_OWNER_PATHS
            or path_matches_any(item, policy["always_human_paths"])
        ):
            owner_paths.add(item)
            guarded.add(item)

    if owner_paths:
        lane = OWNER
    elif guarded:
        lane = OWNER if policy["human_merge_required"] else PROTECTED
    else:
        lane = ROUTINE

    return {
        "lane": lane,
        "protected_paths": sorted(guarded),
        "owner_paths": sorted(owner_paths),
        "requires_owner": lane == OWNER,
        "requires_exact_head_review": True,
        "requires_exact_head_ci": True,
    }
