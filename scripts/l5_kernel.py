#!/usr/bin/env python3
"""Claude-exact L5 coordination kernel.

This module is credential-free. It evaluates only structured evidence and
coordinates leases/intents through a CAS store. It never treats model prose as
gate evidence and it fails closed on unknown or incomplete state.
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
DANGEROUS = frozenset({"push", "update_branch", "merge", "enqueue", "revert", "reserve_next_wu"})
HARMLESS = frozenset({"comment", "review_request", "ci_rerun"})
MAX_CI_RERUNS = 2
MAX_FIX_ITERATIONS = 5
MAX_REVIEW_ROUNDS = 3
MAX_LEASES = 12


class RepoMode(str, Enum):
    """Repository-wide controller modes."""

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
    """Derived state for one work item/PR."""

    GOVERNANCE_CHANGE = "GOVERNANCE_CHANGE"
    WAIT_CI = "WAIT_CI"
    CI_MISSING = "CI_MISSING"
    CI_RED_INFRA = "CI_RED_INFRA"
    CI_RED_DETERMINISTIC = "CI_RED_DETERMINISTIC"
    BEHIND_BASE = "BEHIND_BASE"
    CI_GREEN_UNREVIEWED = "CI_GREEN_UNREVIEWED"
    INTENT_RESTRAINT_PENDING = "INTENT_RESTRAINT_PENDING"
    INTENT_RESTRAINT_FAILED = "INTENT_RESTRAINT_FAILED"
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
    """Exact state observed before a lease-protected operation."""

    head: str
    base: str
    wu_body_hash: str = ""
    pr_updated_at: str = ""


@dataclass(frozen=True)
class Intent:
    """Write-ahead intent attached to a lease."""

    op_id: str
    idem_key: str
    operation: str
    expected_head: str
    expected_base: str
    epoch: int
    state: str = "PENDING"


@dataclass(frozen=True)
class Lease:
    """CAS lease record with monotonic epoch and version."""

    key: str
    holder: str
    epoch: int
    observed: Observation
    acquired_at: float
    expires_at: float
    version: int
    intent: Intent | None = None
    state: str = "ACTIVE"


@dataclass(frozen=True)
class Budget:
    """Bounded retry/fix/review/lease budget."""

    ci_reruns: int = 0
    fix_iterations: int = 0
    review_rounds: int = 0
    lease_acquisitions: int = 0

    def exhausted(self) -> bool:
        """Return True if any bounded dimension is exhausted."""
        return (
            self.ci_reruns >= MAX_CI_RERUNS
            or self.fix_iterations >= MAX_FIX_ITERATIONS
            or self.review_rounds >= MAX_REVIEW_ROUNDS
            or self.lease_acquisitions >= MAX_LEASES
        )


class CASStore(Protocol):
    """Minimal store interface required by the deterministic kernel."""

    def read(self, key: str) -> Lease | None: ...
    def cas(self, key: str, expected_version: int | None, value: Lease) -> bool: ...
    def read_repo_mode(self, repo_id: str) -> tuple[RepoMode, int | None]: ...
    def cas_repo_mode(
        self,
        repo_id: str,
        expected_version: int | None,
        mode: RepoMode,
        *,
        human_clear: bool = False,
        post_merge_verified: bool = False,
    ) -> bool: ...


class MemoryCASStore:
    """Test-only CAS store. Missing repository mode fails closed."""

    def __init__(self) -> None:
        self.leases: dict[str, Lease] = {}
        self.modes: dict[str, tuple[RepoMode, int]] = {}

    def read(self, key: str) -> Lease | None:
        """Read a lease."""
        return self.leases.get(key)

    def cas(self, key: str, expected_version: int | None, value: Lease) -> bool:
        """CAS one lease by record version."""
        cur = self.leases.get(key)
        actual = None if cur is None else cur.version
        if actual != expected_version:
            return False
        self.leases[key] = value
        return True

    def read_repo_mode(self, repo_id: str) -> tuple[RepoMode, int | None]:
        """Read repo mode; missing mode is degraded, never NORMAL."""
        return self.modes.get(repo_id, (RepoMode.AUTOMATION_DEGRADED, None))

    def cas_repo_mode(
        self,
        repo_id: str,
        expected_version: int | None,
        mode: RepoMode,
        *,
        human_clear: bool = False,
        post_merge_verified: bool = False,
    ) -> bool:
        """CAS repo mode while enforcing protected exits."""
        cur = self.modes.get(repo_id)
        actual = None if cur is None else cur[1]
        if actual != expected_version:
            return False
        old_mode = RepoMode.AUTOMATION_DEGRADED if cur is None else cur[0]
        if old_mode in HUMAN_CLEAR_ONLY and old_mode != mode and not human_clear:
            return False
        if old_mode == RepoMode.MERGE_LOCKED and old_mode != mode and not post_merge_verified:
            return False
        self.modes[repo_id] = (mode, 1 if cur is None else cur[1] + 1)
        return True


def new_run_id() -> str:
    """Return a unique invocation identifier."""
    return str(uuid.uuid4())


def idem_key(repo_id: str, item: str, head: str, base: str, operation: str) -> str:
    """Derive a deterministic idempotency key bound to head and base."""
    material = [repo_id, item, head, base, operation]
    return sha256(json.dumps(material, separators=(",", ":")).encode()).hexdigest()


def lease_key(repo_id: str, item_kind: str, item_id: str, op_class: str) -> str:
    """Build a canonical lease key."""
    return f"{repo_id}:{item_kind}:{item_id}:{op_class}"


def repo_merge_lock_key(repo_id: str) -> str:
    """Return the singleton repository merge-lock key."""
    return lease_key(repo_id, "repo", repo_id, "REPO_MERGE_LOCK")


def capacity_slot_key(repo_id: str, slot: int) -> str:
    """Return a canonical capacity slot key."""
    if type(slot) is not int or slot < 1:
        raise ValueError("CAPACITY_SLOT_INVALID")
    return lease_key(repo_id, "capacity", str(slot), f"CAPACITY_SLOT_{slot}")


def acquire(
    store: CASStore,
    key: str,
    holder: str,
    observed: Observation,
    *,
    now_srv: float,
    ttl: float = 300,
) -> Lease | None:
    """Acquire an expired/free lease, preserving monotonic epoch/version."""
    if ttl <= 0:
        raise ValueError("LEASE_TTL_INVALID")
    cur = store.read(key)
    if cur and cur.expires_at > now_srv:
        return None
    if cur and cur.intent and cur.intent.state == "PENDING":
        return None
    epoch = 1 if cur is None else cur.epoch + 1
    version = 1 if cur is None else cur.version + 1
    nxt = Lease(key, holder, epoch, observed, now_srv, now_srv + ttl, version)
    expected = None if cur is None else cur.version
    return nxt if store.cas(key, expected, nxt) else None


def renew(
    store: CASStore,
    lease: Lease,
    *,
    now_srv: float,
    ttl: float = 300,
) -> Lease | None:
    """Renew only the exact current, still-live lease."""
    if ttl <= 0 or now_srv >= lease.expires_at or lease.state != "ACTIVE":
        return None
    new_expires_at = now_srv + ttl
    if new_expires_at <= lease.expires_at:
        return None
    cur = store.read(lease.key)
    if cur != lease or cur.holder != lease.holder or cur.epoch != lease.epoch or cur.state != "ACTIVE":
        return None
    nxt = replace(lease, expires_at=new_expires_at, version=lease.version + 1)
    return nxt if store.cas(lease.key, lease.version, nxt) else None


def attach_intent(
    store: CASStore,
    lease: Lease,
    repo_id: str,
    item: str,
    operation: str,
    *,
    now_srv: float,
) -> Lease | None:
    """Attach one PENDING intent to the exact current live lease."""
    if operation not in DANGEROUS | HARMLESS or now_srv >= lease.expires_at or lease.state != "ACTIVE":
        return None
    cur = store.read(lease.key)
    if cur != lease or cur.holder != lease.holder or cur.epoch != lease.epoch:
        return None
    if cur.intent is not None and cur.intent.state == "PENDING":
        return None
    intent = Intent(
        str(uuid.uuid4()),
        idem_key(repo_id, item, lease.observed.head, lease.observed.base, operation),
        operation,
        lease.observed.head,
        lease.observed.base,
        lease.epoch,
    )
    nxt = replace(cur, intent=intent, version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None


def resolve_intent(store: CASStore, lease: Lease, state: str) -> Lease | None:
    """Resolve the exact current PENDING intent as DONE or ABORTED."""
    if state not in {"DONE", "ABORTED"}:
        raise ValueError("INTENT_RESOLUTION_INVALID")
    cur = store.read(lease.key)
    if cur != lease or cur.intent is None or cur.intent.state != "PENDING":
        return None
    nxt = replace(cur, intent=replace(cur.intent, state=state), version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None


def verify_intent(store: CASStore, lease: Lease) -> Lease | None:
    """Durably mark a completed main-changing intent as post-merge verified."""
    cur = store.read(lease.key)
    if cur != lease or cur.intent is None or cur.intent.state != "DONE":
        return None
    nxt = replace(cur, intent=replace(cur.intent, state="VERIFIED"), version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None


def release(store: CASStore, lease: Lease, *, now_srv: float) -> Lease | None:
    """Release only the exact current lease after any intent is terminal."""
    cur = store.read(lease.key)
    if cur != lease or cur.state != "ACTIVE":
        return None
    if cur.intent is not None and cur.intent.state == "PENDING":
        return None
    nxt = replace(cur, expires_at=now_srv, version=cur.version + 1, state="RELEASED")
    return nxt if store.cas(cur.key, cur.version, nxt) else None


def intent_recovery(lease: Lease, detection_result: str) -> str:
    """Map readback evidence for an orphaned PENDING intent."""
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
) -> tuple[bool, str]:
    """Revalidate exact lease, observation, intent, and repository mode."""
    cur = store.read(lease.key)
    if cur is None:
        return False, "LEASE_MISSING"
    if cur != lease:
        return False, "LEASE_LOST"
    if cur.state != "ACTIVE":
        return False, "LEASE_RELEASED"
    if now_srv + max_write_latency + skew_margin >= cur.expires_at:
        return False, "LEASE_TOO_CLOSE_TO_EXPIRY"
    if cur.observed != observed_now:
        return False, "OBSERVATION_CHANGED"
    if cur.intent is None or cur.intent.state != "PENDING" or cur.intent.epoch != cur.epoch:
        return False, "INTENT_INVALID"
    if cur.intent.operation not in DANGEROUS | HARMLESS:
        return False, "OPERATION_NOT_ALLOWLISTED"

    mode, _ = store.read_repo_mode(repo_id)
    if mode in HUMAN_CLEAR_ONLY:
        return False, f"REPO_MODE_{mode.value}"
    if mode == RepoMode.MAIN_BROKEN:
        return (
            (True, "OK")
            if cur.intent.operation == "revert"
            else (False, "REPO_MODE_MAIN_BROKEN")
        )
    if mode != RepoMode.NORMAL:
        return False, f"REPO_MODE_{mode.value}"
    return True, "OK"


def governance_mode(snapshot: Mapping[str, Any]) -> RepoMode:
    """Derive repository mode from live structured governance evidence."""
    if snapshot.get("halted") is True:
        return RepoMode.HALTED
    if snapshot.get("controller_integrity_failure") is True:
        return RepoMode.CONTROLLER_INTEGRITY
    if snapshot.get("security_integrity_failure") is True:
        return RepoMode.SECURITY_INTEGRITY_FAILURE
    if snapshot.get("ledger_reachable") is not True:
        return RepoMode.AUTOMATION_DEGRADED
    governance_fields = (
        "platform_enforcement_ok",
        "live_rules_at_least_pinned",
        "rulesets_or_protection_active",
        "required_check_sources_pinned",
    )
    if (
        not all(snapshot.get(k) is True for k in governance_fields)
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
    """Return True only for a 40-character hex SHA."""
    return isinstance(value, str) and bool(SHA40.fullmatch(value))


def _source_key(value: Any) -> tuple[str, str] | None:
    """Normalize a required check source."""
    if not isinstance(value, Mapping):
        return None
    app = value.get("app_id")
    path = value.get("workflow_path")
    if not isinstance(app, (str, int)) or not isinstance(path, str) or not path:
        return None
    return str(app), path


def _checks_ok(
    rows: Any,
    head: str,
    base: str,
    expected_sources: Any,
) -> bool:
    """Validate exact-head/base, source-pinned, complete check history."""
    if not isinstance(rows, list) or not isinstance(expected_sources, list) or not expected_sources:
        return False
    expected = [_source_key(x) for x in expected_sources]
    if any(x is None for x in expected) or len(set(expected)) != len(expected):
        return False

    by_source: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return False
        key = _source_key(row)
        if key is not None:
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
        if row.get("assertion_failure_any_attempt") is not False:
            return False
        if row.get("attempt_history_complete") is not True:
            return False
        if row.get("source_verified") is not True:
            return False
    return True


def _review_ok(review: Any, head: str, base: str) -> bool:
    """Validate exact-head independent review and authorship provenance."""
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
        "reviewer_eligible": True,
        "authorship_complete": True,
        "material_authors_head_sha": head,
        "identity_source_verified": True,
    }
    if any(review.get(k) != v for k, v in required.items()):
        return False
    reviewer = review.get("author")
    authors = review.get("material_authors")
    controllers = review.get("controller_identities")
    if not isinstance(reviewer, str) or not reviewer:
        return False
    if not isinstance(authors, list) or not isinstance(controllers, list):
        return False
    norm = reviewer.strip().lower()
    return norm not in {str(x).strip().lower() for x in authors + controllers}



INTENT_RESTRAINT_REASON_CODES = frozenset(
    {
        "INTENT_DRIFT",
        "OVERENGINEERED",
        "DUPLICATED_MECHANISM",
        "PERFORMANCE_REGRESSION",
        "SEMANTIC_CHANGE",
        "DIFF_DISPROPORTIONATE",
        "CONVENTION_DRIFT",
        "ARCHITECTURE_DRIFT",
        "UNRESOLVED_DELETION_CANDIDATES",
        "SELF_REVIEW",
        "ATTESTATION_INCOMPLETE",
    }
)


def intent_restraint_status(snapshot: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    """Validate a structured, independent engineering-intent attestation.

    The attestation is bound to the exact head, base, and frozen work-unit body
    hash. Model prose is never accepted as gate evidence.
    """
    evidence = snapshot.get("intent_restraint")
    if evidence is None:
        return "PENDING", ("INTENT_RESTRAINT_MISSING",)
    if not isinstance(evidence, Mapping):
        return "FAILED", ("ATTESTATION_INCOMPLETE",)
    state = evidence.get("state")
    if state == "PENDING":
        return "PENDING", ("INTENT_RESTRAINT_PENDING",)
    if state != "PASS":
        reasons = evidence.get("failure_reasons")
        if not isinstance(reasons, list) or not reasons:
            return "FAILED", ("ATTESTATION_INCOMPLETE",)
        normalized = tuple(str(reason) for reason in reasons)
        if any(reason not in INTENT_RESTRAINT_REASON_CODES for reason in normalized):
            return "FAILED", ("ATTESTATION_INCOMPLETE",)
        return "FAILED", normalized

    head = snapshot.get("head_sha")
    base = snapshot.get("base_sha")
    wu_hash = snapshot.get("wu_body_hash")
    failures: list[str] = []
    if not _sha(head) or evidence.get("head_sha") != head:
        failures.append("INTENT_DRIFT")
    if not _sha(base) or evidence.get("base_sha") != base:
        failures.append("INTENT_DRIFT")
    if not isinstance(wu_hash, str) or not wu_hash or evidence.get("wu_body_hash") != wu_hash:
        failures.append("INTENT_DRIFT")
    if evidence.get("material_authors_head_sha") != head:
        failures.append("INTENT_DRIFT")

    required_true = {
        "complete": "ATTESTATION_INCOMPLETE",
        "designated_independent": "SELF_REVIEW",
        "reviewer_eligible": "SELF_REVIEW",
        "identity_source_verified": "ATTESTATION_INCOMPLETE",
        "wu_contract_frozen": "INTENT_DRIFT",
        "intent_preserved": "INTENT_DRIFT",
        "scope_discipline_verified": "INTENT_DRIFT",
        "minimal_change_verified": "OVERENGINEERED",
        "no_overengineering": "OVERENGINEERED",
        "existing_mechanism_reused_or_justified": "DUPLICATED_MECHANISM",
        "conventions_preserved": "CONVENTION_DRIFT",
        "architecture_consistent": "ARCHITECTURE_DRIFT",
        "performance_preserved": "PERFORMANCE_REGRESSION",
        "api_semantics_preserved": "SEMANTIC_CHANGE",
        "diff_proportionate": "DIFF_DISPROPORTIONATE",
        "adversarial_deletion_review_complete": "ATTESTATION_INCOMPLETE",
        "deletion_candidates_resolved": "UNRESOLVED_DELETION_CANDIDATES",
    }
    for key, reason in required_true.items():
        if evidence.get(key) is not True:
            failures.append(reason)

    reasons = evidence.get("failure_reasons")
    if reasons != []:
        failures.append("ATTESTATION_INCOMPLETE")

    reviewer = evidence.get("author")
    authors = evidence.get("material_authors")
    controllers = evidence.get("controller_identities")
    if not isinstance(reviewer, str) or not reviewer.strip():
        failures.append("ATTESTATION_INCOMPLETE")
    elif not isinstance(authors, list) or not isinstance(controllers, list):
        failures.append("ATTESTATION_INCOMPLETE")
    else:
        norm = reviewer.strip().lower()
        excluded = {str(actor).strip().lower() for actor in authors + controllers}
        if norm in excluded:
            failures.append("SELF_REVIEW")

    unique = tuple(dict.fromkeys(failures))
    return ("PASS", ()) if not unique else ("FAILED", unique)


def intent_restraint_ok(snapshot: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Return a fail-closed boolean view of the intent/restraint gate."""
    state, reasons = intent_restraint_status(snapshot)
    return state == "PASS", reasons


def merge_ok_v11(snapshot: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Evaluate base MERGE_OK plus the L5.1 Engineering Intent & Restraint gate."""
    base_ok, base_failures = merge_ok(snapshot)
    if snapshot.get("l5_intent_restraint_required") is not True:
        return base_ok, base_failures
    restraint_ok, restraint_failures = intent_restraint_ok(snapshot)
    failures = tuple(base_failures) + tuple(restraint_failures)
    return base_ok and restraint_ok, failures


def merge_precheck_v11(snapshot: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Evaluate merge readiness before runtime-only lock/fence acquisition."""
    staged = dict(snapshot)
    staged["merge_lock_owned"] = True
    staged["fence_ok"] = True
    staged["unresolved_other_intent"] = False
    return merge_ok_v11(staged)


TRUE_FIELDS = (
    "merge_lock_owned",
    "fence_ok",
    "pr_open",
    "same_repo",
    "base_ref_expected",
    "head_ref_matches_api",
    "base_currency_ok",
    "mergeable",
    "mergeable_state_clean",
    "live_rules_at_least_pinned",
    "rulesets_or_protection_active",
    "files_fully_enumerated",
    "diff_within_limit",
    "adapter_hash_ok",
    "controller_hash_ok",
    "code_scanning_present",
    "review_decision_ok",
    "findings_confirmed_closed",
    "thread_resolution_policy_ok",
    "human_gate_checks_ok",
    "dependencies_verified",
    "required_check_sources_pinned",
    "credential_isolation_ok",
    "secret_hygiene_ok",
)
FALSE_FIELDS = (
    "global_halted",
    "repo_halted",
    "unresolved_other_intent",
    "pr_draft",
    "pr_locked",
    "fork_pr",
    "controller_admin",
    "controller_bypass",
    "governed_path_touched",
    "test_weakening",
    "new_security_alert",
    "secret_finding",
    "later_changes_requested",
    "unresolved_required_threads",
    "human_hold",
)


def merge_ok(snapshot: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Evaluate Claude's fail-closed structured autonomous merge predicate."""
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
    if not (
        _sha(head)
        and _sha(base)
        and _checks_ok(
            snapshot.get("required_checks"),
            head,
            base,
            snapshot.get("required_check_sources"),
        )
    ):
        failures.append("REQUIRED_CHECKS_INVALID")
    if not (
        _sha(head)
        and _sha(base)
        and _checks_ok(
            snapshot.get("security_checks"),
            head,
            base,
            snapshot.get("security_check_sources"),
        )
    ):
        failures.append("SECURITY_CHECKS_INVALID")
    if not (_sha(head) and _sha(base) and _review_ok(snapshot.get("review"), head, base)):
        failures.append("REVIEW_INVALID")
    return not failures, tuple(failures)


def classify_item(snapshot: Mapping[str, Any], budget: Budget) -> ItemState:
    """Derive item state from current evidence only."""
    if budget.exhausted():
        return ItemState.PARKED
    if snapshot.get("no_actionable_work") is True:
        return ItemState.IDLE
    if snapshot.get("governed_path_touched") is True or snapshot.get("test_weakening") is True:
        return ItemState.GOVERNANCE_CHANGE
    if snapshot.get("needs_human") is True or snapshot.get("human_hold") is True:
        return ItemState.BLOCK_HUMAN
    if snapshot.get("dependency_wait") is True:
        return ItemState.WAIT_DEPENDENCY
    if snapshot.get("merged") is True:
        if snapshot.get("main_broken") is True:
            return ItemState.MAIN_BROKEN
        if snapshot.get("post_merge_verified") is True:
            return ItemState.MERGED_VERIFIED
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
    if snapshot.get("l5_intent_restraint_required") is True:
        restraint_state, _ = intent_restraint_status(snapshot)
        if restraint_state == "PENDING":
            return ItemState.INTENT_RESTRAINT_PENDING
        if restraint_state != "PASS":
            return ItemState.INTENT_RESTRAINT_FAILED
        ok, failures = merge_precheck_v11(snapshot)
    else:
        staged = dict(snapshot)
        staged["merge_lock_owned"] = True
        staged["fence_ok"] = True
        staged["unresolved_other_intent"] = False
        ok, failures = merge_ok(staged)
    if ok:
        return ItemState.MERGE_ELIGIBLE
    finding_codes = {
        "FINDINGS_CONFIRMED_CLOSED_NOT_TRUE",
        "UNRESOLVED_REQUIRED_THREADS_NOT_FALSE",
        "THREAD_RESOLUTION_POLICY_OK_NOT_TRUE",
    }
    if failures and set(failures).issubset(finding_codes):
        return ItemState.FINDINGS_OPEN
    return ItemState.BLOCK_HUMAN


def selftest() -> None:
    """Run a minimal safety smoke test."""
    store = MemoryCASStore()
    store.cas_repo_mode("repo", None, RepoMode.NORMAL)
    obs = Observation("a" * 40, "b" * 40, "wu", "t")
    lease = acquire(store, lease_key("repo", "pr", "1", "MERGE"), new_run_id(), obs, now_srv=1000)
    assert lease is not None
    with_intent = attach_intent(store, lease, "repo", "pr:1", "merge", now_srv=1001)
    assert with_intent is not None
    assert fence_ok(store, "repo", with_intent, obs, now_srv=1010) == (True, "OK")
    assert intent_recovery(with_intent, "UNKNOWN") == "READBACK_REQUIRED"
    assert release(store, with_intent, now_srv=1011) is None
    resolved = resolve_intent(store, with_intent, "DONE")
    assert resolved is not None
    assert release(store, resolved, now_srv=1012) is not None
    print("l5_kernel selftest PASS")


if __name__ == "__main__":
    selftest()
