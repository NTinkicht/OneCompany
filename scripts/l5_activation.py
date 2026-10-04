#!/usr/bin/env python3
"""Fail-closed L5 mutation authorization over the certified recovery planner."""
from __future__ import annotations

# Keep the pre-attestation surface to CPython built-in/frozen modules only.
# Candidate-local stdlib/L5 siblings are not importable until the source-loaded
# bootstrap has removed bytecode and (for ACTIVE) certified the runtime closure.
import os
import sys


def _load_bootstrap_runtime_from_source():
    """Load bootstrap source without consulting Python import/bytecode caches."""
    scripts = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(scripts)
    source_path = os.path.join(scripts, "control_plane_bootstrap.py")
    for parent in (root, scripts, os.path.join(root, ".l5")):
        if os.path.islink(parent) or not os.path.isdir(parent):
            raise RuntimeError("L5_BOOTSTRAP_RUNTIME_ROOT_INVALID")
    if os.path.islink(source_path) or not os.path.isfile(source_path):
        raise RuntimeError("L5_BOOTSTRAP_SOURCE_INVALID")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(source_path, flags)
    except OSError as exc:
        raise RuntimeError("L5_BOOTSTRAP_SOURCE_UNAVAILABLE") from exc
    try:
        info = os.fstat(fd)
        if (info.st_mode & 0o170000) != 0o100000:
            raise RuntimeError("L5_BOOTSTRAP_SOURCE_INVALID")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            source = handle.read()
    finally:
        os.close(fd)

    sys.dont_write_bytecode = True
    module = type(sys)("control_plane_bootstrap")
    module.__file__ = source_path
    module.__package__ = ""
    try:
        code = compile(source, source_path, "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except Exception as exc:
        raise RuntimeError("L5_BOOTSTRAP_SOURCE_EXECUTION_FAILED") from exc
    runtime = module.__dict__.get("bootstrap_runtime")
    if not callable(runtime):
        raise RuntimeError("L5_BOOTSTRAP_RUNTIME_MISSING")
    sys.modules["control_plane_bootstrap"] = module
    return runtime


bootstrap_runtime = _load_bootstrap_runtime_from_source()
_bootstrap_ok, _bootstrap_reason = bootstrap_runtime()
if not _bootstrap_ok:
    raise RuntimeError(_bootstrap_reason)

# Import non-frozen stdlib with repository/PYTHONPATH entries excluded. This
# prevents LIVE_SAFE imports from executing candidate-local stdlib shadows.
_scripts = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_scripts)
_saved_path = list(sys.path)
_env_paths = {
    os.path.abspath(entry)
    for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep)
    if entry
}
_blocked_paths = {
    os.path.abspath(_root),
    os.path.abspath(_scripts),
    os.path.abspath(os.getcwd()),
    *_env_paths,
}
try:
    sys.path[:] = [
        entry for entry in sys.path
        if entry and os.path.abspath(entry) not in _blocked_paths
    ]
    import hashlib  # noqa: E402
    import json  # noqa: E402
    import re  # noqa: E402
    from typing import Any  # noqa: E402
finally:
    sys.path[:] = _saved_path

from l5_control_plane import mutation_policy  # noqa: E402

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
    """Read one required boolean or fail closed on unknown evidence."""
    value = row.get(key)
    if type(value) is not bool:
        raise ValueError(f"L5_ACTIVATION_{key.upper()}_UNKNOWN")
    return value


def _token_set(values: Any) -> set[str]:
    """Validate the prior mutation-token history."""
    if values is None:
        return set()
    if not isinstance(values, set) or not all(isinstance(v, str) and TOKEN64.fullmatch(v) for v in values):
        raise ValueError("L5_ACTIVATION_TOKEN_HISTORY_INVALID")
    return values


def _mutation_token(plan: dict[str, Any], snapshot: dict[str, Any]) -> str:
    """Bind one idempotency token to the exact planned mutation and refs."""
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


def _recovery_api():
    """Load the certified recovery planner only after control-plane preflight."""
    from l5_recovery import MAX_RETRIES, plan_recovery

    return MAX_RETRIES, plan_recovery


def _trust_boundary(snapshot: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Load and evaluate reviewer trust only after control-plane preflight."""
    from l5_trust_boundary import trust_boundary_from_activation

    return trust_boundary_from_activation(snapshot)


def authorize_mutation(
    snapshot: dict[str, Any],
    *,
    prior_mutation_tokens: set[str] | None = None,
    enforce_control_plane: bool = True,
) -> dict[str, Any]:
    """Authorize one exact mutation.

    ``enforce_control_plane=False`` exists only for non-mutating recovery of an
    already persisted token. Callers must never use it to admit a new write.
    """
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

    if enforce_control_plane:
        preflight_ok, preflight_reason = mutation_policy(None)
        if not preflight_ok:
            return {
                "authorized": False,
                "mutation_allowed": False,
                "reason": preflight_reason,
                "expected_head_sha": head,
                "expected_base_sha": base,
            }

    max_retries, plan_recovery = _recovery_api()
    plan = plan_recovery(snapshot)
    action = plan.get("next_action")
    if action not in SAFE_MUTATIONS:
        return {"authorized": False, "mutation_allowed": False, "reason": "ACTION_NOT_MUTATION_WHITELISTED", "planned_action": action}
    mutation = SAFE_MUTATIONS[action]
    if enforce_control_plane:
        mode_ok, mode_reason = mutation_policy(mutation)
        if not mode_ok:
            return {
                "authorized": False,
                "mutation_allowed": False,
                "reason": mode_reason,
                "mutation": mutation,
                "expected_head_sha": head,
                "expected_base_sha": base,
            }
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
        trust_ok, trust_failures = _trust_boundary(snapshot)
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
        if type(count) is not int or not 1 <= count <= max_retries or not isinstance(result["retry_action_after"], str):
            raise ValueError("L5_ACTIVATION_RETRY_STATE_INVALID")
    if mutation == "reserve_next_wu":
        selected = plan.get("selected_issue")
        if type(selected) is not int or selected < 1:
            raise ValueError("L5_ACTIVATION_SELECTED_ISSUE_INVALID")
        result["selected_issue"] = selected
    return result
