#!/usr/bin/env python3
"""Read-only L5 shadow evaluator used before platform enforcement is installed."""
from __future__ import annotations

from typing import Any, Mapping

from l5_kernel import Budget, RepoMode, classify_item, governance_mode, merge_precheck_v11

PLATFORM_FIELDS = (
    "platform_enforcement_ok",
    "live_rules_at_least_pinned",
    "rulesets_or_protection_active",
    "required_check_sources_pinned",
)


def shadow_evaluate(
    repo_snapshot: Mapping[str, Any],
    item_snapshot: Mapping[str, Any],
    *,
    budget: Budget | None = None,
) -> Mapping[str, Any]:
    """Compute a candidate L5 decision while making writes structurally impossible."""
    state = classify_item(item_snapshot, budget or Budget())
    platform_deferred = not all(repo_snapshot.get(name) is True for name in PLATFORM_FIELDS)

    staged_repo = dict(repo_snapshot)
    for name in PLATFORM_FIELDS:
        staged_repo[name] = True
    staged_mode = governance_mode(staged_repo)

    staged_item = dict(item_snapshot)
    staged_item["live_rules_at_least_pinned"] = True
    staged_item["rulesets_or_protection_active"] = True
    staged_item["required_check_sources_pinned"] = True
    staged_item["repo_mode"] = staged_mode.value
    staged_item["l5_intent_restraint_required"] = True
    hypothetical_ok, hypothetical_failures = merge_precheck_v11(staged_item)

    blockers: list[str] = []
    if platform_deferred:
        blockers.append("PLATFORM_ENFORCEMENT_DEFERRED")
    if staged_mode != RepoMode.NORMAL:
        blockers.append(f"STAGED_REPO_MODE_{staged_mode.value}")

    return {
        "mode": "SHADOW",
        "mutation_allowed": False,
        "writes": 0,
        "state": state.value,
        "activation_blockers": blockers,
        "candidate_merge_ok_if_platform_enforced": hypothetical_ok,
        "candidate_merge_failures_if_platform_enforced": list(hypothetical_failures),
    }


def evaluate_shadow(
    repo_snapshot: Mapping[str, Any],
    item_snapshot: Mapping[str, Any],
    *,
    budget: Budget | None = None,
) -> Mapping[str, Any]:
    """Backward-compatible public entrypoint for the read-only shadow evaluator."""
    return shadow_evaluate(repo_snapshot, item_snapshot, budget=budget)
