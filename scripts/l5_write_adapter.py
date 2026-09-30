#!/usr/bin/env python3
"""Credential-isolated L5 write adapter with live CAS and replay safety."""
from __future__ import annotations

import json
from typing import Any

from l5_activation import HARD_BOUNDARY_FIELDS, RETRYABLE_MUTATIONS, SAFE_MUTATIONS, TOKEN64, authorize_mutation, required_bool

MUTATIONS = frozenset(SAFE_MUTATIONS.values())


class LostResponse(Exception):
    pass


class AlreadyExists(Exception):
    pass


class WriteRejected(Exception):
    pass


def stream_key(auth: dict[str, Any], snapshot: dict[str, Any]) -> str:
    return json.dumps([snapshot.get("repository"), auth.get("issue"), auth.get("canonical_pr")], separators=(",", ":"))


def _blocked(reason: str, token: Any = None) -> dict[str, Any]:
    return {"status": "BLOCKED", "reason": reason, "mutation_token": token, "written": False}


def _live_gate(auth: dict[str, Any], stream: str, client: Any, store: Any, *, retry_check: bool) -> str | None:
    boundaries = client.fetch_boundaries()
    if not isinstance(boundaries, dict):
        return "BOUNDARY_STATE_UNKNOWN"
    try:
        if any(required_bool(boundaries, key) for key in HARD_BOUNDARY_FIELDS):
            return "HARD_BOUNDARY"
    except ValueError:
        return "BOUNDARY_STATE_UNKNOWN"
    live = client.fetch_live(auth["canonical_pr"])
    if not isinstance(live, dict):
        return "LIVE_STATE_UNKNOWN"
    if live.get("head_sha") != auth["expected_head_sha"] or live.get("base_sha") != auth["expected_base_sha"]:
        return "STALE_HEAD_OR_BASE"
    mutation = auth["mutation"]
    expected_state = "merged" if mutation == "reserve_next_wu" else "open"
    if live.get("pr_state") != expected_state:
        return "PR_STATE_MISMATCH"
    streams = live.get("open_streams")
    if not isinstance(streams, dict):
        return "LIVE_STATE_UNKNOWN"
    if mutation == "reserve_next_wu":
        if any(bool(prs) for prs in streams.values()):
            return "DUPLICATE_STREAM"
    elif streams.get(auth["issue"]) != [auth["canonical_pr"]] or sum(len(v) for v in streams.values()) != 1:
        return "DUPLICATE_STREAM"
    if mutation == "dispatch_review" and live.get("review_eligible_nonauthor") is not True:
        return "REVIEWER_NOT_ELIGIBLE"
    if retry_check and mutation in RETRYABLE_MUTATIONS:
        prior_count, prior_scope = store.retry_state(stream)
        scope = auth.get("retry_action_after")
        expected = auth.get("retry_count_after")
        if (prior_count if prior_scope == scope else 0) + 1 != expected:
            return "RETRY_STATE_STALE"
    return None


def _params(auth: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_pr": auth["canonical_pr"], "issue": auth["issue"],
        "expected_head_sha": auth["expected_head_sha"], "expected_base_sha": auth["expected_base_sha"],
        "selected_issue": auth.get("selected_issue"), "idempotency_key": auth["mutation_token"],
    }


def _reconcile(auth: dict[str, Any], client: Any, store: Any, *, written: bool) -> dict[str, Any]:
    token = auth["mutation_token"]
    if client.verify_effect(auth["mutation"], _params(auth)) is True:
        store.set_status(token, "COMPLETE")
        return {"status": "COMPLETE", "reason": "EFFECT_VERIFIED", "mutation_token": token, "written": written}
    store.set_status(token, "VERIFICATION_FAILED")
    return {"status": "VERIFICATION_FAILED", "reason": "EFFECT_NOT_OBSERVED", "mutation_token": token, "written": written}


def execute_mutation(auth: dict[str, Any], snapshot: dict[str, Any], client: Any, store: Any) -> dict[str, Any]:
    token = auth.get("mutation_token") if isinstance(auth, dict) else None
    if not isinstance(auth, dict) or auth.get("authorized") is not True or auth.get("mutation_allowed") is not True:
        return _blocked("NOT_AUTHORIZED", token)
    if auth.get("mutation") not in MUTATIONS or not isinstance(token, str) or not TOKEN64.fullmatch(token):
        return _blocked("AUTHORIZATION_INVALID", token)
    try:
        reproduced = authorize_mutation(snapshot)
    except ValueError:
        return _blocked("AUTHORIZATION_NOT_REPRODUCIBLE", token)
    if reproduced != auth:
        return _blocked("AUTHORIZATION_MISMATCH", token)
    stream = stream_key(auth, snapshot)
    prior = store.get(token)
    if prior:
        if prior.get("status") == "COMPLETE":
            return {"status": "REPLAY_NOOP", "reason": "ALREADY_COMPLETE", "mutation_token": token, "written": False}
        if prior.get("status") == "PENDING":
            return _reconcile(auth, client, store, written=False)
        return _blocked(f"PRIOR_{prior.get('status')}", token)
    reason = _live_gate(auth, stream, client, store, retry_check=True)
    if reason:
        return _blocked(reason, token)
    record = {"status": "PENDING", "mutation": auth["mutation"], "canonical_pr": auth["canonical_pr"]}
    if not store.begin(token, record, stream, auth.get("retry_count_after"), auth.get("retry_action_after")):
        return {"status": "REPLAY_NOOP", "reason": "TOKEN_ALREADY_PERSISTED", "mutation_token": token, "written": False}
    reason = _live_gate(auth, stream, client, store, retry_check=False)
    if reason:
        store.set_status(token, "FAILED", reason)
        return _blocked(reason, token)
    try:
        client.perform(auth["mutation"], _params(auth))
    except WriteRejected:
        store.set_status(token, "FAILED", "WRITE_REJECTED")
        return {"status": "FAILED", "reason": "WRITE_REJECTED", "mutation_token": token, "written": False}
    except (LostResponse, AlreadyExists):
        return _reconcile(auth, client, store, written=False)
    return _reconcile(auth, client, store, written=True)


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.retry: dict[str, tuple[int, str | None]] = {}

    def get(self, token: str) -> dict[str, Any] | None:
        return dict(self.records[token]) if token in self.records else None

    def begin(self, token: str, record: dict[str, Any], stream: str, count: int | None, action: str | None) -> bool:
        if token in self.records:
            return False
        self.records[token] = dict(record)
        if count is not None:
            self.retry[stream] = (count, action)
        return True

    def set_status(self, token: str, status: str, detail: Any = None) -> None:
        self.records[token]["status"] = status
        self.records[token]["detail"] = detail

    def retry_state(self, stream: str) -> tuple[int, str | None]:
        return self.retry.get(stream, (0, None))
