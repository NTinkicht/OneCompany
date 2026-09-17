#!/usr/bin/env python3
"""Reconcile event wake hints into bounded, non-authoritative handoff proposals."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from typing import Any

from onecompany_lib import CONTROL, load_json

CONFIG_PATH = CONTROL / "handoffs.json"
HINT_KINDS = {
    "WORK_READY",
    "LEASE_CHANGED",
    "PR_CHANGED",
    "CI_CHANGED",
    "REVIEW_CHANGED",
    "MERGE_CHANGED",
    "RECONCILE",
}
TRANSITION_KINDS = HINT_KINDS - {"RECONCILE"}
CONSEQUENTIAL_KINDS = {"WORK_READY", "LEASE_CHANGED", "REVIEW_CHANGED", "MERGE_CHANGED"}
PROPOSAL_SCHEMA = "onecompany-handoff-proposal-v1"


class HandoffError(ValueError):
    """Raised when staged handoff input violates the reconciliation contract."""


def load_policy() -> dict[str, Any]:
    """Load the reviewed staged handoff policy."""
    value = load_json(CONFIG_PATH)
    if not isinstance(value, dict):
        raise HandoffError("handoff policy must be an object")
    return value


def activation_ready(policy: dict[str, Any]) -> bool:
    """Return whether separately reviewed activation evidence is fully present."""
    activation = policy.get("activation") or {}
    refs = activation.get("evidence_refs")
    return bool(
        policy.get("enabled") is True
        and policy.get("mode") == "active"
        and activation.get("requires_b1_protected_main") is True
        and activation.get("requires_ledger_replay_proof") is True
        and activation.get("b1_protected_main_proven") is True
        and activation.get("ledger_replay_proven") is True
        and isinstance(refs, list)
        and bool(refs)
    )


def publisher_allowed(policy: dict[str, Any], publisher: str, event_type: str) -> bool:
    """Require both publisher identity and event type to be explicitly allowlisted."""
    publisher_policy = policy.get("publisher_policy") or {}
    if publisher_policy.get("publisher_identity_and_event_type_both_required") is not True:
        return False
    mapping = publisher_policy.get("automation_publishers")
    if not isinstance(mapping, dict):
        return False
    allowed = mapping.get(publisher)
    return isinstance(allowed, list) and event_type in allowed


def _validate_hint(hint: Any, policy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(hint, dict):
        raise HandoffError("wake hint must be an object")
    event_id = hint.get("event_id")
    kind = hint.get("kind")
    subject = hint.get("subject")
    if not isinstance(event_id, str) or not event_id:
        raise HandoffError("wake hint requires event_id")
    if kind not in HINT_KINDS or kind not in set(policy.get("wake_hints") or []):
        raise HandoffError(f"unsupported wake hint kind:{kind}")
    if not isinstance(subject, str) or not subject:
        raise HandoffError("wake hint requires subject")
    payload = hint.get("payload", {})
    if not isinstance(payload, dict):
        raise HandoffError("wake hint payload must be an object")

    publisher = hint.get("publisher")
    event_type = hint.get("event_type")
    if publisher is not None or event_type is not None:
        if not isinstance(publisher, str) or not isinstance(event_type, str):
            raise HandoffError("publisher-scoped hint requires publisher and event_type")
        if not publisher_allowed(policy, publisher, event_type):
            raise HandoffError("publisher_or_event_type_not_allowlisted")
    return hint


def _validate_authoritative(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise HandoffError("authoritative snapshot must be an object")
    repository = snapshot.get("repository")
    state = snapshot.get("subject_state")
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise HandoffError("authoritative snapshot repository is invalid")
    if not isinstance(snapshot.get("emergency_stop"), bool):
        raise HandoffError("authoritative snapshot requires emergency_stop boolean")
    if not isinstance(snapshot.get("zero_spend_ok"), bool):
        raise HandoffError("authoritative snapshot requires zero_spend_ok boolean")
    if not isinstance(state, dict):
        raise HandoffError("authoritative snapshot requires subject_state object")
    return snapshot


def _effective_kind(hint: dict[str, Any], snapshot: dict[str, Any]) -> str:
    kind = str(hint["kind"])
    if kind != "RECONCILE":
        return kind
    transition = snapshot.get("transition_kind")
    if transition not in TRANSITION_KINDS:
        raise HandoffError("RECONCILE requires authoritative transition_kind")
    return str(transition)


def _require_keys(state: dict[str, Any], names: tuple[str, ...], kind: str) -> None:
    missing = [name for name in names if name not in state]
    if missing:
        raise HandoffError(f"{kind} authoritative state missing:{','.join(missing)}")


def _projection(kind: str, state: dict[str, Any]) -> dict[str, Any]:
    """Select only authoritative fields that define one logical handoff state."""
    fields: dict[str, tuple[str, ...]] = {
        "WORK_READY": (
            "work_unit",
            "status",
            "dependencies_satisfied",
            "active_writer_count",
            "route_eligible",
        ),
        "LEASE_CHANGED": (
            "work_unit",
            "canonical",
            "role",
            "actor",
            "branch",
            "pr",
            "dispatch_eligible",
            "active_writer_count",
        ),
        "PR_CHANGED": ("pr", "head", "base"),
        "CI_CHANGED": ("pr", "head", "base", "ci_state"),
        "REVIEW_CHANGED": (
            "pr",
            "head",
            "base",
            "review_head",
            "review_base",
            "independent",
            "human_code_owner_required",
            "human_code_owner_approved",
        ),
        "MERGE_CHANGED": (
            "pr",
            "head",
            "base",
            "verified",
            "already_processed",
            "successors",
        ),
    }
    names = fields[kind]
    _require_keys(state, names, kind)
    return {name: copy.deepcopy(state[name]) for name in names}


def _idempotency_key(repository: str, subject: str, kind: str, state: dict[str, Any]) -> str:
    material = {
        "repository": repository,
        "subject": subject,
        "kind": kind,
        "state": _projection(kind, state),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decision(kind: str, snapshot: dict[str, Any]) -> tuple[str, list[str]]:
    state = snapshot["subject_state"]
    _projection(kind, state)

    if snapshot["emergency_stop"] and kind in CONSEQUENTIAL_KINDS:
        return "STOPPED", ["emergency_stop_active"]
    if not snapshot["zero_spend_ok"] and kind in {"WORK_READY", "LEASE_CHANGED"}:
        return "CAPACITY_BLOCKED", ["zero_extra_spend_not_verified"]

    if kind == "WORK_READY":
        reasons: list[str] = []
        if state["status"] != "READY":
            reasons.append("work_not_ready")
        if state["dependencies_satisfied"] is not True:
            reasons.append("dependencies_not_satisfied")
        if state["route_eligible"] is not True:
            reasons.append("no_verified_zero_spend_route")
        if state["active_writer_count"] != 0:
            reasons.append("canonical_writer_already_exists")
        return ("DISPATCH_PROPOSAL", []) if not reasons else ("NO_ACTION", reasons)

    if kind == "LEASE_CHANGED":
        reasons = []
        if state["canonical"] is not True or state["role"] != "implementation":
            reasons.append("canonical_implementation_lease_not_verified")
        if state["dispatch_eligible"] is not True:
            reasons.append("dispatch_path_not_verified")
        if state["active_writer_count"] != 1:
            reasons.append("canonical_writer_count_not_one")
        return ("EXECUTION_PROPOSAL", []) if not reasons else ("NO_ACTION", reasons)

    if kind == "PR_CHANGED":
        return "EVIDENCE_RECONCILE", []

    if kind == "CI_CHANGED":
        if state["ci_state"] == "success":
            return "EVIDENCE_RECONCILE", []
        return "CI_BLOCKED", [f"ci_state:{state['ci_state']}"]

    if kind == "REVIEW_CHANGED":
        if state["review_head"] != state["head"] or state["review_base"] != state["base"]:
            return "NO_ACTION", ["stale_review_identity"]
        if state["independent"] is not True:
            return "NO_ACTION", ["reviewer_not_independent"]
        if state["human_code_owner_required"] is True and state["human_code_owner_approved"] is not True:
            return "HUMAN_GATE_PENDING", ["required_human_code_owner_not_approved"]
        return "PROMOTION_RECONCILE", []

    if state["verified"] is not True:
        return "NO_ACTION", ["merge_not_verified_from_live_github"]
    if state["already_processed"] is True:
        return "NO_ACTION", ["merge_already_processed"]
    return "SUCCESSOR_DISCOVERY", []


def reconcile_hint(
    hint: Any,
    authoritative_snapshot: Any,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile one untrusted wake hint against authoritative state without mutating."""
    policy = copy.deepcopy(policy) if policy is not None else load_policy()
    hint = _validate_hint(hint, policy)
    snapshot = _validate_authoritative(authoritative_snapshot)
    kind = _effective_kind(hint, snapshot)
    state = snapshot["subject_state"]
    action, reasons = _decision(kind, snapshot)
    ready = activation_ready(policy)
    return {
        "schema": PROPOSAL_SCHEMA,
        "authority": "none",
        "authority_effects": [],
        "repository": snapshot["repository"],
        "subject": hint["subject"],
        "effective_kind": kind,
        "action": action,
        "reasons": reasons,
        "idempotency_key": _idempotency_key(
            snapshot["repository"], str(hint["subject"]), kind, state
        ),
        "activation_state": "PROPOSAL_READY" if ready else "STAGED_BLOCKED",
        "proposal_only": True,
        "may_mutate": False,
        "hint_payload_used_as_authority": False,
        "authoritative_state": _projection(kind, state),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile a staged event-driven handoff")
    parser.add_argument("--hint-json", required=True)
    parser.add_argument("--authoritative-json", required=True)
    args = parser.parse_args()
    try:
        hint = json.loads(args.hint_json)
        snapshot = json.loads(args.authoritative_json)
        print(json.dumps(reconcile_hint(hint, snapshot), indent=2, sort_keys=True))
        return 0
    except (json.JSONDecodeError, HandoffError) as exc:
        print(f"HANDOFF BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
