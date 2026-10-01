#!/usr/bin/env python3
"""Credential-isolated L5 write adapter with atomic CAS and replay safety."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

from l5_activation import HARD_BOUNDARY_FIELDS, RETRYABLE_MUTATIONS, SAFE_MUTATIONS, TOKEN64, authorize_mutation, required_bool

MUTATIONS = frozenset(SAFE_MUTATIONS.values())
REVIEW_SENSITIVE = frozenset({"dispatch_review", "merge_expected_head"})
_UNSET = object()


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


def _live_gate(auth: dict[str, Any], stream: str, client: Any, store: Any, *, retry_check: bool, observed_retry: tuple[int, str | None] | None = None) -> str | None:
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
    if mutation in REVIEW_SENSITIVE and live.get("review_eligible_nonauthor") is not True:
        return "REVIEWER_NOT_ELIGIBLE"
    if retry_check and mutation in RETRYABLE_MUTATIONS:
        prior_count, prior_scope = observed_retry if observed_retry is not None else store.retry_state(stream)
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
    return {"status": "IN_PROGRESS", "reason": "EFFECT_NOT_YET_VERIFIED", "mutation_token": token, "written": written}


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
        status = prior.get("status")
        if status == "COMPLETE":
            return {"status": "REPLAY_NOOP", "reason": "ALREADY_COMPLETE", "mutation_token": token, "written": False}
        if status == "PENDING":
            return _reconcile(auth, client, store, written=False)
        if status != "RETRYABLE":
            return _blocked(f"PRIOR_{status}", token)

    observed_retry = store.retry_state(stream) if auth["mutation"] in RETRYABLE_MUTATIONS else None
    observed_owner = store.retry_owner(stream) if auth["mutation"] in RETRYABLE_MUTATIONS else _UNSET
    reason = _live_gate(auth, stream, client, store, retry_check=True, observed_retry=observed_retry)
    if reason:
        return _blocked(reason, token)
    perform_cas = getattr(client, "perform_cas", None)
    if not callable(perform_cas):
        return _blocked("ATOMIC_CAS_UNAVAILABLE", token)
    record = {"status": "PENDING", "mutation": auth["mutation"], "canonical_pr": auth["canonical_pr"],
              "expected_head_sha": auth["expected_head_sha"], "expected_base_sha": auth["expected_base_sha"]}
    started = store.begin(
        token, record, stream, auth.get("retry_count_after"), auth.get("retry_action_after"),
        expected_retry=observed_retry, expected_owner=observed_owner,
    )
    if not started:
        existing = store.get(token)
        if existing is not None and existing.get("status") == "PENDING":
            return {"status": "REPLAY_NOOP", "reason": "TOKEN_ALREADY_PERSISTED", "mutation_token": token, "written": False}
        return _blocked("RETRY_STATE_STALE", token)
    try:
        reason = _live_gate(auth, stream, client, store, retry_check=False)
    except Exception as exc:
        store.fail_and_restore(token, f"{type(exc).__name__}: {exc}", stream, observed_retry)
        return {"status": "FAILED", "reason": "UNEXPECTED_ERROR", "mutation_token": token, "written": False}
    if reason:
        store.fail_and_restore(token, reason, stream, observed_retry)
        return _blocked(reason, token)
    try:
        result = perform_cas(auth["mutation"], _params(auth))
        if result is False:
            raise WriteRejected("ATOMIC_CAS_REJECTED")
        if result is not True:
            return _reconcile(auth, client, store, written=False)
    except WriteRejected as exc:
        store.fail_and_restore(token, str(exc), stream, observed_retry)
        return {"status": "FAILED", "reason": "WRITE_REJECTED", "mutation_token": token, "written": False}
    except Exception:
        return _reconcile(auth, client, store, written=False)
    return _reconcile(auth, client, store, written=True)


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.retry: dict[str, tuple[int, str | None]] = {}
        self.retry_owners: dict[str, str] = {}

    def get(self, token: str) -> dict[str, Any] | None:
        return dict(self.records[token]) if token in self.records else None

    def begin(self, token: str, record: dict[str, Any], stream: str, count: int | None, action: str | None,
              *, expected_retry: tuple[int, str | None] | None = None, expected_owner: Any = _UNSET) -> bool:
        existing = self.records.get(token)
        if existing is not None and existing.get("status") != "RETRYABLE":
            return False
        if expected_retry is not None and self.retry.get(stream, (0, None)) != expected_retry:
            return False
        if expected_owner is not _UNSET and self.retry_owners.get(stream) != expected_owner:
            return False
        row = dict(record)
        if expected_retry is not None:
            row["retry_before"] = list(expected_retry)
        if count is not None:
            row["retry_written"] = [count, action]
        self.records[token] = row
        if count is not None:
            self.retry[stream] = (count, action)
            self.retry_owners[stream] = token
        return True

    def fail_and_restore(self, token: str, detail: Any, stream: str, prior_retry: tuple[int, str | None] | None) -> None:
        row = self.records[token]
        row["status"] = "RETRYABLE"
        row["detail"] = detail
        if prior_retry is None:
            return
        written = row.get("retry_written")
        if not isinstance(written, list) or len(written) != 2:
            return
        if self.retry.get(stream, (0, None)) != (written[0], written[1]) or self.retry_owners.get(stream) != token:
            return
        if prior_retry == (0, None):
            self.retry.pop(stream, None)
        else:
            self.retry[stream] = prior_retry
        # Keep this token as the monotonic owner/version tag; an older attempt can no longer win an ABA race.

    def set_status(self, token: str, status: str, detail: Any = None) -> None:
        self.records[token]["status"] = status
        self.records[token]["detail"] = detail

    def retry_state(self, stream: str) -> tuple[int, str | None]:
        return self.retry.get(stream, (0, None))

    def retry_owner(self, stream: str) -> str | None:
        return self.retry_owners.get(stream)


class JsonFileStore(MemoryStore):
    """Crash-safe process-shared token/retry store guarded by flock."""
    def __init__(self, path: Path) -> None:
        super().__init__(); self.path = Path(path)

    def _locked(self, fn: Any) -> Any:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.path) + ".lock", "w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.records = data["records"]
                self.retry = {k: (v[0], v[1]) for k, v in data["retry"].items()}
                self.retry_owners = dict(data.get("retry_owners", {}))
            else:
                self.records, self.retry, self.retry_owners = {}, {}, {}
            out = fn()
            tmp = self.path.with_suffix(".tmp")
            payload = json.dumps({
                "records": self.records,
                "retry": {k: list(v) for k, v in self.retry.items()},
                "retry_owners": self.retry_owners,
            }, sort_keys=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(payload); fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
            try: os.fsync(dir_fd)
            finally: os.close(dir_fd)
            return out

    def get(self, token: str) -> dict[str, Any] | None:
        return self._locked(lambda: MemoryStore.get(self, token))

    def begin(self, token: str, record: dict[str, Any], stream: str, count: int | None, action: str | None,
              *, expected_retry: tuple[int, str | None] | None = None, expected_owner: Any = _UNSET) -> bool:
        return self._locked(lambda: MemoryStore.begin(
            self, token, record, stream, count, action,
            expected_retry=expected_retry, expected_owner=expected_owner,
        ))

    def fail_and_restore(self, token: str, detail: Any, stream: str, prior_retry: tuple[int, str | None] | None) -> None:
        self._locked(lambda: MemoryStore.fail_and_restore(self, token, detail, stream, prior_retry))

    def set_status(self, token: str, status: str, detail: Any = None) -> None:
        self._locked(lambda: MemoryStore.set_status(self, token, status, detail))

    def retry_state(self, stream: str) -> tuple[int, str | None]:
        return self._locked(lambda: MemoryStore.retry_state(self, stream))

    def retry_owner(self, stream: str) -> str | None:
        return self._locked(lambda: MemoryStore.retry_owner(self, stream))
