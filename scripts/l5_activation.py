#!/usr/bin/env python3
"""Fail-closed L5 mutation authorization over the certified recovery planner."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from l5_control_plane import mutation_policy
from l5_recovery import MAX_RETRIES, plan_recovery
from l5_trust_boundary import trust_boundary_from_activation

SHA40 = re.compile(r"^[0-9a-f]{40}$")
TOKEN64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_MUTATIONS = {
    "REMEDIATE_SAME_PR_CI": "retry_ci",
    "DISPATCH_ELIGIBLE_NONAUTHOR_REVIEW": "dispatch_review",
    "FAILOVER_TO_ELIGIBLE_NONAUTHOR_REVIEWER": "dispatch_review",
    "REMEDIATE_SAME_PR_REVIEW": "remediate_review",
    "AWAIT_AUTHORIZED_EXPECTED_HEAD_MERGE": "merge_expected_head",
    "PLAN_REPLENISH_READY_WU": "reserve_next_wu",
    "RECONCILE_HEAD_BASE": "update_branch",
}
HARD_BOUNDARY_FIELDS = (
    "emergency_stop", "human_only", "blocked", "release_go_no_go",
    "destructive_production", "spend_required", "secret_scope_change",
    "security_control_weakening",
)
RETRYABLE_MUTATIONS = frozenset({"retry_ci", "dispatch_review", "remediate_review", "update_branch"})


def required_bool(row: dict[str, Any], key: str) -> bool:
    value = row.get(key)
    if type(value) is not bool:
        raise ValueError(f"L5_ACTIVATION_{key.upper()}_UNKNOWN")
    return value


def _token_set(values: Any) -> set[str]:
    if values is None:
        return set()
    if not isinstance(values, set) or not all(isinstance(v, str) and TOKEN64.fullmatch(v) for v in values):
        raise ValueError("L5_ACTIVATION_TOKEN_HISTORY_INVALID")
    return values


def _mutation_token(plan: dict[str, Any], snapshot: dict[str, Any]) -> str:
    payload = {
        "repository": snapshot.get("repository"),
        "issue": plan.get("issue"),
        "canonical_pr": plan.get("canonical_pr"),
        "mutation": SAFE_MUTATIONS.get(plan.get("action")),
        "expected_head_sha": plan.get("expected_head_sha"),
        "expected_base_sha": plan.get("expected_base_sha"),
        "retry_count_after": plan.get("retry_count_after"),
        "retry_action_after": plan.get("retry_action_after"),
        "selected_issue": plan.get("selected_issue"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def authorize_mutation(snapshot: dict[str, Any], *, enforce_control_plane: bool = True) -> dict[str, Any]:
    for field in HARD_BOUNDARY_FIELDS:
        if required_bool(snapshot, field):
            return {"authorized": False, "mutation_allowed": False, "reason": "HARD_BOUNDARY"}
    plan = plan_recovery(snapshot)
    mutation = SAFE_MUTATIONS.get(plan.get("action"))
    if mutation is None:
        return {"authorized": False, "mutation_allowed": False, "reason": plan.get("action", "NO_SAFE_MUTATION")}
    head = plan.get("expected_head_sha")
    base = plan.get("expected_base_sha")
    if not isinstance(head, str) or not SHA40.fullmatch(head) or not isinstance(base, str) or not SHA40.fullmatch(base):
        return {"authorized": False, "mutation_allowed": False, "reason": "EXACT_STATE_UNKNOWN"}
    if enforce_control_plane:
        control_allowed, control_reason = mutation_policy(mutation)
        if not control_allowed:
            return {"authorized": False, "mutation_allowed": False, "reason": control_reason}
    if mutation == "merge_expected_head":
        trust_ok, trust_failures = trust_boundary_from_activation(snapshot)
        if not trust_ok:
            return {"authorized": False, "mutation_allowed": False, "reason": "TRUST_BOUNDARY_FAILED", "failures": list(trust_failures)}
    retry_count = plan.get("retry_count_after")
    if retry_count is not None and (not isinstance(retry_count, int) or isinstance(retry_count, bool) or retry_count < 1 or retry_count > MAX_RETRIES):
        return {"authorized": False, "mutation_allowed": False, "reason": "RETRY_BUDGET_INVALID"}
    token = _mutation_token(plan, snapshot)
    if token in _token_set(snapshot.get("completed_mutation_tokens")):
        return {"authorized": False, "mutation_allowed": False, "reason": "MUTATION_ALREADY_COMPLETE", "mutation_token": token}
    return {
        "authorized": True,
        "mutation_allowed": True,
        "reason": "AUTHORIZED",
        "mutation": mutation,
        "mutation_token": token,
        "issue": plan.get("issue"),
        "canonical_pr": plan.get("canonical_pr"),
        "expected_head_sha": head,
        "expected_base_sha": base,
        "retry_count_after": retry_count,
        "retry_action_after": plan.get("retry_action_after"),
        "selected_issue": plan.get("selected_issue"),
    }
