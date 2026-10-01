#!/usr/bin/env python3
"""Fail-closed L5 mutation authorization over the certified recovery planner."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

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
RETRYABLE_MUTATIONS = frozenset({"retry_ci", "dispatch_review", "remediate_review"})


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
    material = {
        "mutation": SAFE_MUTATIONS.get(plan.get("next_action")),
        "next_action": plan.get("next_action"),
        "repository": snapshot.get("repository"),
        "issue": snapshot.get("issue"),
        "canonical_pr": snapshot.get("canonical_pr"),
        "head_sha": snapshot.get("head_sha"),
        "base_sha": snapshot.get("base_sha"),
        "selected_issue": plan.get("selected_issue"),
        "retry_action_after": plan.get("retry_action_after"),
        "retry_count_after": plan.get("retry_count_after"),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def authorize_mutation(snapshot: dict[str, Any], *, prior_mutation_tokens: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise ValueError("L5_ACTIVATION_SNAPSHOT_INVALID")
    history = _token_set(prior_mutation_tokens)
    boundaries = {key: required_bool(snapshot, key) for key in HARD_BOUNDARY_FIELDS}
    if any(boundaries.values()):
        return {"authorized": False, "mutation_allowed": False, "reason": "HARD_BOUNDARY"}
    head, base = snapshot.get("head_sha"), snapshot.get("base_sha")
    if not isinstance(head, str) or not SHA40.fullmatch(head) or not isinstance(base, str) or not SHA40.fullmatch(base):
        raise ValueError("L5_ACTIVATION_EXACT_REFS_INVALID")
    if required_bool(snapshot, "head_current") is not True or required_bool(snapshot, "base_current") is not True:
        return {"authorized": False, "mutation_allowed": False, "reason": "STALE_HEAD_OR_BASE"}
    plan = plan_recovery(snapshot)
    action = plan.get("next_action")
    if action not in SAFE_MUTATIONS:
        return {"authorized": False, "mutation_allowed": False, "reason": "ACTION_NOT_MUTATION_WHITELISTED", "planned_action": action}
    mutation = SAFE_MUTATIONS[action]
    token = _mutation_token(plan, snapshot)
    if token in history:
        return {"authorized": False, "mutation_allowed": False, "reason": "REPLAY_NOOP", "mutation_token": token}
    pr, issue = snapshot.get("canonical_pr"), snapshot.get("issue")
    if type(pr) is not int or pr < 1 or type(issue) is not int or issue < 1:
        raise ValueError("L5_ACTIVATION_STREAM_INVALID")
    result = {
        "authorized": True, "mutation_allowed": True, "reason": "AUTHORIZED",
        "mutation": mutation, "mutation_token": token,
        "expected_head_sha": head, "expected_base_sha": base,
        "canonical_pr": pr, "issue": issue,
        "retry_count_after": plan.get("retry_count_after"),
        "retry_action_after": plan.get("retry_action_after"),
    }
    if mutation == "merge_expected_head":
        if plan.get("status") != "READY" or snapshot.get("ci") != "SUCCESS":
            raise ValueError("L5_ACTIVATION_MERGE_EVIDENCE_NOT_READY")
        if required_bool(snapshot, "unresolved_threads") or required_bool(snapshot, "mergeable") is not True:
            raise ValueError("L5_ACTIVATION_MERGE_BLOCKED")
        trust_ok, trust_failures = trust_boundary_from_activation(snapshot)
        if not trust_ok:
            return {
                "authorized": False,
                "mutation_allowed": False,
                "reason": "TRUST_BOUNDARY_FAILED",
                "trust_failures": list(trust_failures),
                "expected_head_sha": head,
                "expected_base_sha": base,
                "canonical_pr": pr,
                "issue": issue,
            }
    if mutation in RETRYABLE_MUTATIONS:
        count = result["retry_count_after"]
        if type(count) is not int or not 1 <= count <= MAX_RETRIES or not isinstance(result["retry_action_after"], str):
            raise ValueError("L5_ACTIVATION_RETRY_STATE_INVALID")
    if mutation == "reserve_next_wu":
        selected = plan.get("selected_issue")
        if type(selected) is not int or selected < 1:
            raise ValueError("L5_ACTIVATION_SELECTED_ISSUE_INVALID")
        result["selected_issue"] = selected
    return result
