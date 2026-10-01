#!/usr/bin/env python3
"""L5 deterministic coordination kernel.

Safety kernel for peer scheduled controllers.  LLM output is never gate evidence.
This module deliberately contains no GitHub/network credentials or repository-code
execution.  Durable deployments must back KernelStore with a real CAS store.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from hashlib import sha256
import json
import time
import uuid
from typing import Any, Protocol


class RepoMode(str, Enum):
    NORMAL = "NORMAL"
    MERGE_LOCKED = "MERGE_LOCKED"
    MAIN_BROKEN = "MAIN_BROKEN"
    MAIN_BROKEN_ENV = "MAIN_BROKEN_ENV"
    AUTOMATION_DEGRADED = "AUTOMATION_DEGRADED"
    PROVIDER_THROTTLED = "PROVIDER_THROTTLED"
    GOVERNANCE_DRIFT = "GOVERNANCE_DRIFT"
    SECURITY_INTEGRITY_FAILURE = "SECURITY_INTEGRITY_FAILURE"
    CONTROLLER_INTEGRITY = "CONTROLLER_INTEGRITY"
    HALTED = "HALTED"


HUMAN_CLEAR_ONLY = frozenset({
    RepoMode.HALTED,
    RepoMode.CONTROLLER_INTEGRITY,
    RepoMode.SECURITY_INTEGRITY_FAILURE,
    RepoMode.GOVERNANCE_DRIFT,
})

DANGEROUS_OPS = frozenset({"push", "update_branch", "merge", "enqueue", "revert"})
HARMLESS_OPS = frozenset({"label", "comment", "review_request", "ci_rerun"})


@dataclass(frozen=True)
class Observation:
    head: str
    base: str
    wu_body_hash: str = ""
    pr_updated_at: str = ""


@dataclass(frozen=True)
class Intent:
    op_id: str
    idem_key: str
    operation: str
    expected_head: str
    expected_base: str
    epoch: int
    state: str = "PENDING"


@dataclass(frozen=True)
class Lease:
    key: str
    holder: str
    epoch: int
    observed: Observation
    acquired_at: float
    expires_at: float
    version: int
    intent: Intent | None = None


class CASStore(Protocol):
    def read(self, key: str) -> Lease | None: ...
    def cas(self, key: str, expected_version: int | None, value: Lease) -> bool: ...
    def repo_mode(self, repo_id: str) -> RepoMode: ...


class MemoryCASStore:
    """Test store only. Production must use a cross-run authoritative CAS store."""
    def __init__(self) -> None:
        self.leases: dict[str, Lease] = {}
        self.modes: dict[str, RepoMode] = {}

    def read(self, key: str) -> Lease | None:
        return self.leases.get(key)

    def cas(self, key: str, expected_version: int | None, value: Lease) -> bool:
        cur = self.leases.get(key)
        actual = None if cur is None else cur.version
        if actual != expected_version:
            return False
        self.leases[key] = value
        return True

    def repo_mode(self, repo_id: str) -> RepoMode:
        return self.modes.get(repo_id, RepoMode.NORMAL)


def new_run_id() -> str:
    return str(uuid.uuid4())


def idem_key(repo_id: str, item: str, head: str, operation: str) -> str:
    raw = json.dumps([repo_id, item, head, operation], separators=(",", ":"))
    return sha256(raw.encode()).hexdigest()


def acquire(store: CASStore, key: str, holder: str, observed: Observation, *, now: float | None = None, ttl: int = 300) -> Lease | None:
    now = time.time() if now is None else now
    current = store.read(key)
    if current and current.expires_at > now:
        return None
    if current and current.intent and current.intent.state == "PENDING":
        return None  # INTENT_RECOVERY must resolve it first.
    epoch = 1 if current is None else current.epoch + 1
    version = 1 if current is None else current.version + 1
    lease = Lease(key, holder, epoch, observed, now, now + ttl, version)
    return lease if store.cas(key, None if current is None else current.version, lease) else None


def attach_intent(store: CASStore, lease: Lease, repo_id: str, item: str, operation: str) -> Lease | None:
    current = store.read(lease.key)
    if current != lease or current.holder != lease.holder or current.epoch != lease.epoch:
        return None
    intent = Intent(str(uuid.uuid4()), idem_key(repo_id, item, lease.observed.head, operation), operation,
                    lease.observed.head, lease.observed.base, lease.epoch)
    updated = Lease(**{**asdict(lease), "observed": lease.observed, "intent": intent, "version": lease.version + 1})
    return updated if store.cas(lease.key, lease.version, updated) else None


def fence_ok(store: CASStore, repo_id: str, lease: Lease, observed_now: Observation, *, now: float | None = None,
             max_write_latency: int = 30, skew_margin: int = 30) -> tuple[bool, str]:
    now = time.time() if now is None else now
    current = store.read(lease.key)
    if current is None or current.holder != lease.holder or current.epoch != lease.epoch or current.version != lease.version:
        return False, "LEASE_LOST"
    if now + max_write_latency + skew_margin >= current.expires_at:
        return False, "LEASE_TOO_CLOSE_TO_EXPIRY"
    if current.observed != observed_now:
        return False, "OBSERVATION_CHANGED"
    if current.intent is None or current.intent.state != "PENDING" or current.intent.epoch != current.epoch:
        return False, "INTENT_INVALID"
    mode = store.repo_mode(repo_id)
    if mode != RepoMode.NORMAL and current.intent.operation not in {"revert", "comment"}:
        return False, f"REPO_MODE_{mode.value}"
    if current.intent.operation not in DANGEROUS_OPS | HARMLESS_OPS:
        return False, "OPERATION_NOT_ALLOWLISTED"
    return True, "OK"


def selftest() -> None:
    s = MemoryCASStore(); obs = Observation("a" * 40, "b" * 40); run = new_run_id()
    l = acquire(s, "repo:pr:1:MERGE", run, obs, now=1000)
    assert l is not None
    assert acquire(s, l.key, new_run_id(), obs, now=1001) is None
    li = attach_intent(s, l, "repo", "pr:1", "merge")
    assert li is not None
    assert fence_ok(s, "repo", li, obs, now=1010) == (True, "OK")
    changed = Observation("c" * 40, "b" * 40)
    assert fence_ok(s, "repo", li, changed, now=1010)[0] is False
    print("l5_kernel selftest PASS")


if __name__ == "__main__":
    selftest()
