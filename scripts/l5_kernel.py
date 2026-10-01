#!/usr/bin/env python3
"""Claude hostile-design L5 coordination kernel.

Credential-free deterministic policy and coordination primitives. Gate evidence
must be structured and authenticated by trusted adapters; model prose is never
gate evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
import json
import re
import uuid
from typing import Any, Mapping, Protocol

SHA40 = re.compile(r"^[0-9a-fA-F]{40}$")
DANGEROUS = frozenset({"push", "update_branch", "merge", "enqueue", "revert"})
HARMLESS = frozenset({"label", "comment", "review_request", "ci_rerun"})
MAX_CI_RERUNS = 2
MAX_FIX_ITERATIONS = 5
MAX_REVIEW_ROUNDS = 3
MAX_LEASES = 12


class RepoMode(str, Enum):
    """Repository-wide execution modes."""

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
    ARCHIVED_PERMISSION_LOST = "ARCHIVED_PERMISSION_LOST"


HUMAN_CLEAR_ONLY = frozenset(
    {
        RepoMode.HALTED,
        RepoMode.CONTROLLER_INTEGRITY,
        RepoMode.SECURITY_INTEGRITY_FAILURE,
        RepoMode.GOVERNANCE_DRIFT,
    }
)


class ItemState(str, Enum):
    """Derived item states reconstructed from current evidence."""

    GOVERNANCE_CHANGE = "GOVERNANCE_CHANGE"
    WAIT_CI = "WAIT_CI"
    CI_MISSING = "CI_MISSING"
    CI_RED_INFRA = "CI_RED_INFRA"
    CI_RED_DETERMINISTIC = "CI_RED_DETERMINISTIC"
    BEHIND_BASE = "BEHIND_BASE"
    CI_GREEN_UNREVIEWED = "CI_GREEN_UNREVIEWED"
    FINDINGS_OPEN = "FINDINGS_OPEN"
    DISPUTED_FINDING = "DISPUTED_FINDING"
    BLOCK_HUMAN = "BLOCK_HUMAN"
    WAIT_DEPENDENCY = "WAIT_DEPENDENCY"
    MERGE_ELIGIBLE = "MERGE_ELIGIBLE"
    MERGE_QUEUED = "MERGE_QUEUED"
    MERGE_OUTCOME_UNKNOWN = "MERGE_OUTCOME_UNKNOWN"
    MERGED_UNVERIFIED = "MERGED_UNVERIFIED"
    MERGED_VERIFIED = "MERGED_VERIFIED"
    MAIN_BROKEN = "MAIN_BROKEN"
    REVERT_PENDING = "REVERT_PENDING"
    SUPERSEDED = "SUPERSEDED"
    PARKED = "PARKED"
    WAIT_PROVIDER = "WAIT_PROVIDER"
    IMPLEMENT = "IMPLEMENT"
    IDLE = "IDLE"


@dataclass(frozen=True)
class Observation:
    """Resource identity captured before a write."""

    head: str
    base: str
    wu_body_hash: str = ""
    pr_updated_at: str = ""


@dataclass(frozen=True)
class Intent:
    """Write-ahead intent persisted before a material mutation."""

    op_id: str
    idem_key: str
    operation: str
    expected_head: str
    expected_base: str
    epoch: int
    state: str = "PENDING"


@dataclass(frozen=True)
class Lease:
    """CAS lease with monotonic epoch and record version."""

    key: str
    holder: str
    epoch: int
    observed: Observation
    acquired_at: float
    expires_at: float
    version: int
    intent: Intent | None = None
    active: bool = True


@dataclass(frozen=True)
class Budget:
    """Bounded retry counters."""

    ci_reruns: int = 0
    fix_iterations: int = 0
    review_rounds: int = 0
    lease_acquisitions: int = 0

    def exhausted(self) -> bool:
        """Return whether any hard retry budget is exhausted."""
        return (
            self.ci_reruns >= MAX_CI_RERUNS
            or self.fix_iterations >= MAX_FIX_ITERATIONS
            or self.review_rounds >= MAX_REVIEW_ROUNDS
            or self.lease_acquisitions >= MAX_LEASES
        )


class CASStore(Protocol):
    """Minimum durable coordination-store interface."""

    def read(self, key: str) -> Lease | None: ...
    def cas(self, key: str, expected_version: int | None, value: Lease) -> bool: ...
    def read_repo_mode(self, repo_id: str) -> tuple[RepoMode, int | None]: ...
    def cas_repo_mode(self, repo_id: str, expected_version: int | None, mode: RepoMode) -> bool: ...
    def list_leases(self) -> list[Lease]: ...


class MemoryCASStore:
    """Test-only CAS store. Production authority is the durable ledger."""

    def __init__(self) -> None:
        self.leases: dict[str, Lease] = {}
        self.modes: dict[str, tuple[RepoMode, int]] = {}

    def read(self, key: str) -> Lease | None:
        """Read a lease/tombstone."""
        return self.leases.get(key)

    def cas(self, key: str, expected_version: int | None, value: Lease) -> bool:
        """Compare-and-swap a lease record by exact version."""
        cur = self.leases.get(key)
        actual = None if cur is None else cur.version
        if actual != expected_version:
            return False
        self.leases[key] = value
        return True

    def read_repo_mode(self, repo_id: str) -> tuple[RepoMode, int | None]:
        """Read repository mode; tests default to NORMAL."""
        return self.modes.get(repo_id, (RepoMode.NORMAL, None))

    def cas_repo_mode(self, repo_id: str, expected_version: int | None, mode: RepoMode) -> bool:
        """CAS repository mode by exact version."""
        cur = self.modes.get(repo_id)
        actual = None if cur is None else cur[1]
        if actual != expected_version:
            return False
        self.modes[repo_id] = (mode, 1 if cur is None else cur[1] + 1)
        return True

    def list_leases(self) -> list[Lease]:
        """Return current records, including inactive tombstones."""
        return list(self.leases.values())


def new_run_id() -> str:
    """Create a unique controller invocation identity."""
    return str(uuid.uuid4())


def idem_key(repo_id: str, item: str, head: str, operation: str) -> str:
    """Create a stable operation detection/idempotency key."""
    return sha256(json.dumps([repo_id, item, head, operation], separators=(",", ":")).encode()).hexdigest()


def lease_key(repo_id: str, item_kind: str, item_id: str, op_class: str) -> str:
    """Build a canonical coordination key."""
    return f"{repo_id}:{item_kind}:{item_id}:{op_class}"


def repo_merge_lock_key(repo_id: str) -> str:
    """Return the single repository merge-lock key."""
    return lease_key(repo_id, "repo", repo_id, "REPO_MERGE_LOCK")


def capacity_slot_key(repo_id: str, slot: int) -> str:
    """Return a replenishment-capacity lease key."""
    if type(slot) is not int or slot < 1:
        raise ValueError("CAPACITY_SLOT_INVALID")
    return lease_key(repo_id, "capacity", str(slot), f"CAPACITY_SLOT_{slot}")


def acquire(store: CASStore, key: str, holder: str, observed: Observation, *, now_srv: float, ttl: float = 300) -> Lease | None:
    """Acquire/reclaim a lease while preserving monotonic epoch/version."""
    cur = store.read(key)
    if cur and cur.active and cur.expires_at > now_srv:
        return None
    if cur and cur.intent and cur.intent.state == "PENDING":
        return None
    epoch = 1 if cur is None else cur.epoch + 1
    version = 1 if cur is None else cur.version + 1
    nxt = Lease(key, holder, epoch, observed, now_srv, now_srv + ttl, version, intent=None, active=True)
    return nxt if store.cas(key, None if cur is None else cur.version, nxt) else None


def renew(store: CASStore, lease: Lease, *, now_srv: float, ttl: float = 300) -> Lease | None:
    """Renew only the exact current lease record."""
    cur = store.read(lease.key)
    if cur != lease or not cur.active:
        return None
    nxt = replace(cur, expires_at=now_srv + ttl, version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None


def attach_intent(store: CASStore, lease: Lease, repo_id: str, item: str, operation: str) -> Lease | None:
    """Attach exactly one pending intent to the exact current lease."""
    cur = store.read(lease.key)
    if (
        cur != lease
        or not cur.active
        or operation not in DANGEROUS | HARMLESS
        or (cur.intent is not None and cur.intent.state == "PENDING")
    ):
        return None
    intent = Intent(
        str(uuid.uuid4()),
        idem_key(repo_id, item, cur.observed.head, operation),
        operation,
        cur.observed.head,
        cur.observed.base,
        cur.epoch,
    )
    nxt = replace(cur, intent=intent, version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None


def resolve_intent(store: CASStore, lease: Lease, state: str) -> Lease | None:
    """Resolve the exact current pending intent after outcome detection."""
    if state not in {"DONE", "ABORTED"}:
        raise ValueError("INTENT_RESOLUTION_INVALID")
    cur = store.read(lease.key)
    if cur != lease or cur.intent is None or cur.intent.state != "PENDING":
        return None
    nxt = replace(cur, intent=replace(cur.intent, state=state), version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None


def release(store: CASStore, lease: Lease, *, now_srv: float) -> Lease | None:
    """Retire only the exact current lease; unresolved intents forbid release."""
    cur = store.read(lease.key)
    if cur != lease or not cur.active:
        return None
    if cur.intent is not None and cur.intent.state == "PENDING":
        return None
    nxt = replace(cur, active=False, expires_at=now_srv, version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None


def intent_recovery(lease: Lease, detection_result: str) -> str:
    """Map trusted outcome detection into a recovery decision."""
    if lease.intent is None or lease.intent.state != "PENDING":
        return "NO_PENDING_INTENT"
    if detection_result == "APPLIED":
        return "RESOLVE_DONE"
    if detection_result == "NOT_APPLIED":
        return "RESOLVE_ABORTED"
    if detection_result == "UNKNOWN":
        return "READBACK_REQUIRED"
    raise ValueError("DETECTION_RESULT_INVALID")


def fence_ok(
    store: CASStore,
    repo_id: str,
    lease: Lease,
    observed_now: Observation,
    *,
    now_srv: float,
    max_write_latency: float = 30,
    skew_margin: float = 30,
    emergency_revert_authorized: bool = False,
) -> tuple[bool, str]:
    """Evaluate the final resource fence immediately before a write."""
    cur = store.read(lease.key)
    if cur is None:
        return False, "LEASE_MISSING"
    if cur != lease or not cur.active:
        return False, "LEASE_LOST"
    if now_srv + max_write_latency + skew_margin >= cur.expires_at:
        return False, "LEASE_TOO_CLOSE_TO_EXPIRY"
    if cur.observed != observed_now:
        return False, "OBSERVATION_CHANGED"
    if cur.intent is None or cur.intent.state != "PENDING" or cur.intent.epoch != cur.epoch:
        return False, "INTENT_INVALID"
    mode, _ = store.read_repo_mode(repo_id)
    operation = cur.intent.operation
    if operation not in DANGEROUS | HARMLESS:
        return False, "OPERATION_NOT_ALLOWLISTED"
    if mode == RepoMode.NORMAL:
        return True, "OK"
    if operation == "comment":
        return True, "OK"
    if operation == "revert" and mode in {RepoMode.MAIN_BROKEN, RepoMode.MAIN_BROKEN_ENV} and emergency_revert_authorized:
        return True, "OK"
    return False, f"REPO_MODE_{mode.value}"


def governance_mode(snapshot: Mapping[str, Any]) -> RepoMode:
    """Derive fail-closed repository mode from live governance evidence."""
    if snapshot.get("halted") is True:
        return RepoMode.HALTED
    if snapshot.get("controller_integrity_failure") is True:
        return RepoMode.CONTROLLER_INTEGRITY
    if snapshot.get("security_integrity_failure") is True:
        return RepoMode.SECURITY_INTEGRITY_FAILURE
    if snapshot.get("ledger_reachable") is not True:
        return RepoMode.AUTOMATION_DEGRADED
    required = (
        "platform_enforcement_ok",
        "live_rules_at_least_pinned",
        "rulesets_or_protection_active",
        "required_check_sources_pinned",
    )
    if (
        not all(snapshot.get(key) is True for key in required)
        or snapshot.get("controller_admin") is True
        or snapshot.get("controller_bypass") is True
    ):
        return RepoMode.GOVERNANCE_DRIFT
    if snapshot.get("main_broken") is True:
        return RepoMode.MAIN_BROKEN
    if snapshot.get("main_broken_env") is True:
        return RepoMode.MAIN_BROKEN_ENV
    if snapshot.get("automation_degraded") is True:
        return RepoMode.AUTOMATION_DEGRADED
    if snapshot.get("provider_throttled") is True:
        return RepoMode.PROVIDER_THROTTLED
    if snapshot.get("merge_locked") is True:
        return RepoMode.MERGE_LOCKED
    if snapshot.get("archived_or_permission_lost") is True:
        return RepoMode.ARCHIVED_PERMISSION_LOST
    return RepoMode.NORMAL


def _sha(value: Any) -> bool:
    """Return whether value is a full Git SHA."""
    return isinstance(value, str) and bool(SHA40.fullmatch(value))


def _source_key(value: Any) -> tuple[str, str] | None:
    """Normalize a check-source identity."""
    if not isinstance(value, Mapping):
        return None
    app = value.get("app_id")
    path = value.get("workflow_path")
    if not isinstance(app, (str, int)) or not isinstance(path, str) or not path:
        return None
    return str(app), path


def _checks_ok(rows: Any, head: str, base: str, expected_sources: Any) -> bool:
    """Validate exact-source, exact-head/base, full-attempt-history checks."""
    if not isinstance(rows, list) or not isinstance(expected_sources, list) or not expected_sources:
        return False
    expected = [_source_key(source) for source in expected_sources]
    if any(key is None for key in expected) or len(set(expected)) != len(expected):
        return False
    by_source: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = _source_key(row)
        if key is not None and isinstance(row, Mapping):
            by_source.setdefault(key, []).append(row)
    for key in expected:
        candidates = by_source.get(key, [])
        if len(candidates) != 1:
            return False
        row = candidates[0]
        if row.get("head_sha") != head or row.get("tested_base_sha") != base:
            return False
        if row.get("latest_attempt") is not True or row.get("conclusion") != "success":
            return False
        if row.get("assertion_history_complete") is not True:
            return False
        if row.get("assertion_failure_any_attempt") is not False:
            return False
    return True


def _review_ok(review: Any, head: str, base: str) -> bool:
    """Validate exact-head/base complete independent review evidence."""
    if not isinstance(review, Mapping):
        return False
    required = {
        "state": "APPROVED",
        "commit_id": head,
        "base_sha": base,
        "complete": True,
        "skipped": False,
        "covers_full_diff": True,
        "designated_independent": True,
    }
    if any(review.get(key) != value for key, value in required.items()):
        return False
    reviewer = review.get("author")
    authors = review.get("material_authors")
    controllers = review.get("controller_identities")
    if not isinstance(reviewer, str) or not reviewer or not isinstance(authors, list) or not isinstance(controllers, list):
        return False
    normalized = reviewer.strip().lower()
    return normalized not in {str(value).strip().lower() for value in authors + controllers}


TRUE_FIELDS = (
    "merge_lock_owned", "fence_ok", "pr_open", "same_repo", "base_ref_expected",
    "head_ref_matches_api", "base_currency_ok", "mergeable", "mergeable_state_clean",
    "live_rules_at_least_pinned", "rulesets_or_protection_active", "files_fully_enumerated",
    "diff_within_limit", "adapter_hash_ok", "controller_hash_ok", "code_scanning_present",
    "review_decision_ok", "findings_confirmed_closed", "thread_resolution_policy_ok",
    "human_gate_checks_ok", "dependencies_verified", "required_check_sources_pinned",
    "credential_isolation_ok", "secret_hygiene_ok",
)
FALSE_FIELDS = (
    "global_halted", "repo_halted", "unresolved_other_intent", "pr_draft", "pr_locked",
    "fork_pr", "controller_admin", "controller_bypass", "governed_path_touched",
    "test_weakening", "new_security_alert", "secret_finding", "later_changes_requested",
    "unresolved_required_threads", "human_hold",
)


def merge_ok(snapshot: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Evaluate the full fail-closed autonomous merge predicate."""
    failures: list[str] = []
    head = snapshot.get("head_sha")
    base = snapshot.get("base_sha")
    if not _sha(head):
        failures.append("HEAD_UNKNOWN")
    if not _sha(base):
        failures.append("BASE_UNKNOWN")
    if snapshot.get("repo_mode") != RepoMode.NORMAL.value:
        failures.append("REPO_MODE_NOT_NORMAL")
    for key in TRUE_FIELDS:
        if snapshot.get(key) is not True:
            failures.append(key.upper() + "_NOT_TRUE")
    for key in FALSE_FIELDS:
        if snapshot.get(key) is not False:
            failures.append(key.upper() + "_NOT_FALSE")
    if _sha(head) and snapshot.get("expected_head_sha") != head:
        failures.append("EXPECTED_HEAD_MISMATCH")
    if _sha(base) and snapshot.get("expected_base_sha") != base:
        failures.append("EXPECTED_BASE_MISMATCH")
    if not (_sha(head) and _sha(base) and _checks_ok(snapshot.get("required_checks"), head, base, snapshot.get("required_check_sources"))):
        failures.append("REQUIRED_CHECKS_INVALID")
    if not (_sha(head) and _sha(base) and _checks_ok(snapshot.get("security_checks"), head, base, snapshot.get("security_check_sources"))):
        failures.append("SECURITY_CHECKS_INVALID")
    if not (_sha(head) and _sha(base) and _review_ok(snapshot.get("review"), head, base)):
        failures.append("REVIEW_INVALID")
    return not failures, tuple(failures)


def classify_item(snapshot: Mapping[str, Any], budget: Budget) -> ItemState:
    """Derive one item state from fresh evidence."""
    if budget.exhausted():
        return ItemState.PARKED
    if snapshot.get("no_actionable_work") is True:
        return ItemState.IDLE
    if snapshot.get("governed_path_touched") is True or snapshot.get("test_weakening") is True:
        return ItemState.GOVERNANCE_CHANGE
    if snapshot.get("needs_human") is True:
        return ItemState.BLOCK_HUMAN
    if snapshot.get("dependency_wait") is True:
        return ItemState.WAIT_DEPENDENCY
    if snapshot.get("merged") is True:
        if snapshot.get("post_merge_verified") is True:
            return ItemState.MERGED_VERIFIED
        if snapshot.get("main_broken") is True:
            return ItemState.MAIN_BROKEN
        return ItemState.MERGED_UNVERIFIED
    if snapshot.get("merge_outcome_unknown") is True:
        return ItemState.MERGE_OUTCOME_UNKNOWN
    if snapshot.get("merge_queued") is True:
        return ItemState.MERGE_QUEUED
    if snapshot.get("superseded") is True:
        return ItemState.SUPERSEDED
    if snapshot.get("disputed_finding") is True:
        return ItemState.DISPUTED_FINDING
    if snapshot.get("findings_open") is True:
        return ItemState.FINDINGS_OPEN
    if snapshot.get("behind_base") is True:
        return ItemState.BEHIND_BASE
    ci = snapshot.get("ci")
    if ci in (None, "PENDING"):
        return ItemState.WAIT_CI
    if ci == "MISSING":
        return ItemState.CI_MISSING
    if ci == "INFRA_FAILED":
        return ItemState.CI_RED_INFRA
    if ci == "DETERMINISTIC_FAILED":
        return ItemState.CI_RED_DETERMINISTIC
    if ci != "GREEN":
        return ItemState.WAIT_CI
    if snapshot.get("provider_unavailable") is True:
        return ItemState.WAIT_PROVIDER
    if snapshot.get("independent_review_pass") is not True:
        return ItemState.CI_GREEN_UNREVIEWED
    return ItemState.MERGE_ELIGIBLE if merge_ok(snapshot)[0] else ItemState.FINDINGS_OPEN


def selftest() -> None:
    """Exercise the core lease/fence/recovery path."""
    store = MemoryCASStore()
    observed = Observation("a" * 40, "b" * 40, "wu", "t")
    key = lease_key("repo", "pr", "1", "MERGE")
    lease = acquire(store, key, new_run_id(), observed, now_srv=1000)
    assert lease is not None
    intended = attach_intent(store, lease, "repo", "pr:1", "merge")
    assert intended is not None
    assert fence_ok(store, "repo", intended, observed, now_srv=1010) == (True, "OK")
    assert intent_recovery(intended, "UNKNOWN") == "READBACK_REQUIRED"
    resolved = resolve_intent(store, intended, "ABORTED")
    assert resolved is not None
    assert release(store, resolved, now_srv=1020) is not None
    print("l5_kernel selftest PASS")


if __name__ == "__main__":
    selftest()
