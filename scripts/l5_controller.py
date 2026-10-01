#!/usr/bin/env python3
"""Executable Claude-exact L5 BOOT-to-ACTION controller.

The runner reconstructs repository truth every invocation, recovers orphaned
intents before selecting work, acquires one lease, re-observes the resource,
writes one intent, fences again, and delegates the effect to the existing
guarded write adapter. It never waits for CI/review inside one invocation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from l5_kernel import (
    Budget,
    HUMAN_CLEAR_ONLY,
    ItemState,
    Lease,
    MemoryCASStore,
    Observation,
    RepoMode,
    acquire,
    attach_intent,
    capacity_slot_key,
    classify_item,
    fence_ok,
    governance_mode,
    intent_recovery,
    lease_key,
    merge_ok,
    new_run_id,
    repo_merge_lock_key,
    resolve_intent,
)


class RunPhase(str, Enum):
    """Deterministic invocation phases."""

    BOOT = "BOOT"
    HALT_CHECK = "HALT_CHECK"
    GOVERNANCE_AUDIT = "GOVERNANCE_AUDIT"
    REPOSITORY_MODE = "REPOSITORY_MODE"
    INTENT_RECOVERY = "INTENT_RECOVERY"
    INVENTORY = "INVENTORY"
    CLASSIFY = "CLASSIFY"
    SELECT = "SELECT"
    ACQUIRE_CAS_LEASE = "ACQUIRE_CAS_LEASE"
    RECONCILE_ITEM = "RECONCILE_ITEM"
    WRITE_INTENT = "WRITE_INTENT"
    FENCE_CHECK = "FENCE_CHECK"
    ACTION = "ACTION"
    EXIT = "EXIT"


@dataclass(frozen=True)
class RunResult:
    """One invocation result."""

    run_id: str
    phase: RunPhase
    status: str
    action: str | None = None
    item_id: str | None = None
    reason: str | None = None
    mutation_result: Mapping[str, Any] | None = None


class ControllerIO(Protocol):
    """Structured evidence/action boundary required by the runner."""

    def repo_snapshot(self) -> Mapping[str, Any]: ...
    def pending_intent_leases(self) -> Sequence[Lease]: ...
    def detect_intent_effect(self, lease: Lease) -> str: ...
    def inventory(self) -> Sequence[Mapping[str, Any]]: ...
    def budget_for(self, item: Mapping[str, Any]) -> Budget: ...
    def observe_item(self, item: Mapping[str, Any]) -> Observation: ...
    def execute_guarded(
        self,
        operation: str,
        item: Mapping[str, Any],
        lease: Lease,
    ) -> Mapping[str, Any]: ...


def _item_id(item: Mapping[str, Any]) -> str:
    """Return a stable item identifier or fail closed."""
    value = item.get("item_id")
    if not isinstance(value, (str, int)) or str(value) == "":
        raise ValueError("L5_ITEM_ID_INVALID")
    return str(value)


def _state_priority(state: ItemState) -> int:
    """Return deterministic priority; smaller runs first."""
    order = {
        ItemState.MERGED_UNVERIFIED: 0,
        ItemState.MAIN_BROKEN: 1,
        ItemState.CI_RED_DETERMINISTIC: 2,
        ItemState.FINDINGS_OPEN: 3,
        ItemState.CI_RED_INFRA: 4,
        ItemState.BEHIND_BASE: 5,
        ItemState.CI_GREEN_UNREVIEWED: 6,
        ItemState.MERGE_ELIGIBLE: 7,
        ItemState.IMPLEMENT: 8,
        ItemState.IDLE: 9,
    }
    return order.get(state, 100)


def _operation_for(state: ItemState, item: Mapping[str, Any]) -> str | None:
    """Map a derived state to one bounded controller action."""
    if state == ItemState.CI_RED_INFRA:
        return "retry_ci"
    if state == ItemState.CI_RED_DETERMINISTIC:
        return "remediate_review"
    if state == ItemState.CI_GREEN_UNREVIEWED:
        return "dispatch_review"
    if state == ItemState.FINDINGS_OPEN:
        return "remediate_review"
    if state == ItemState.BEHIND_BASE:
        return "update_branch"
    if state == ItemState.MERGE_ELIGIBLE:
        return "merge_expected_head"
    if state == ItemState.MAIN_BROKEN:
        return "revert"
    if state == ItemState.IDLE and item.get("replenish_candidate") is True:
        return "reserve_next_wu"
    return None


def _lease_key_for(repo_id: str, item_id: str, operation: str, item: Mapping[str, Any]) -> str:
    """Choose repo merge lock, capacity slot, or item lease."""
    if operation in {"merge_expected_head", "revert"}:
        return repo_merge_lock_key(repo_id)
    if operation == "reserve_next_wu":
        slot = item.get("capacity_slot")
        if type(slot) is not int:
            raise ValueError("L5_CAPACITY_SLOT_UNKNOWN")
        return capacity_slot_key(repo_id, slot)
    return lease_key(repo_id, "item", item_id, operation.upper())


def _intent_operation(operation: str) -> str:
    """Map controller action to kernel operation class."""
    mapping = {
        "retry_ci": "ci_rerun",
        "dispatch_review": "review_request",
        "remediate_review": "push",
        "update_branch": "update_branch",
        "merge_expected_head": "merge",
        "reserve_next_wu": "reserve_next_wu",
        "revert": "revert",
    }
    try:
        return mapping[operation]
    except KeyError as exc:
        raise ValueError("L5_OPERATION_NOT_ALLOWLISTED") from exc


def _sync_mode(store: MemoryCASStore, repo_id: str, derived: RepoMode) -> tuple[bool, str]:
    """Persist derived mode without auto-clearing human-only modes."""
    current, version = store.read_repo_mode(repo_id)
    if current == derived:
        return True, "UNCHANGED"
    if current in HUMAN_CLEAR_ONLY:
        return False, "HUMAN_CLEAR_REQUIRED"
    if not store.cas_repo_mode(repo_id, version, derived):
        return False, "MODE_CAS_CONFLICT"
    return True, "UPDATED"


def _recover_pending(io: ControllerIO, store: MemoryCASStore) -> tuple[bool, str]:
    """Recover all known orphaned intents before selecting new work."""
    for lease in io.pending_intent_leases():
        current = store.read(lease.key)
        if current != lease:
            return False, "RECOVERY_LEASE_STALE"
        decision = intent_recovery(lease, io.detect_intent_effect(lease))
        if decision == "READBACK_REQUIRED":
            return False, "RECOVERY_READBACK_REQUIRED"
        if decision == "RESOLVE_DONE":
            if resolve_intent(store, lease, "DONE") is None:
                return False, "RECOVERY_CAS_CONFLICT"
        elif decision == "RESOLVE_ABORTED":
            if resolve_intent(store, lease, "ABORTED") is None:
                return False, "RECOVERY_CAS_CONFLICT"
    return True, "RECOVERED"


def _select(io: ControllerIO, items: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ItemState] | None:
    """Classify then deterministically select one actionable item."""
    candidates: list[tuple[int, str, Mapping[str, Any], ItemState]] = []
    for item in items:
        state = classify_item(item, io.budget_for(item))
        if _operation_for(state, item) is None:
            continue
        candidates.append((_state_priority(state), _item_id(item), item, state))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1]))
    _, _, item, state = candidates[0]
    return item, state


def run_once(
    repo_id: str,
    io: ControllerIO,
    store: MemoryCASStore,
    *,
    now_srv: float,
    run_id: str | None = None,
) -> RunResult:
    """Execute one deterministic BOOT-to-ACTION controller invocation."""
    rid = run_id or new_run_id()
    repo = io.repo_snapshot()

    if repo.get("halted") is True:
        return RunResult(rid, RunPhase.HALT_CHECK, "BLOCKED", reason="HALTED")

    derived = governance_mode(repo)
    synced, sync_reason = _sync_mode(store, repo_id, derived)
    if not synced:
        return RunResult(rid, RunPhase.REPOSITORY_MODE, "BLOCKED", reason=sync_reason)
    if derived in HUMAN_CLEAR_ONLY:
        return RunResult(rid, RunPhase.REPOSITORY_MODE, "BLOCKED", reason=derived.value)
    if derived not in {RepoMode.NORMAL, RepoMode.MAIN_BROKEN}:
        return RunResult(rid, RunPhase.REPOSITORY_MODE, "WAIT", reason=derived.value)

    recovered, recovery_reason = _recover_pending(io, store)
    if not recovered:
        return RunResult(rid, RunPhase.INTENT_RECOVERY, "WAIT", reason=recovery_reason)

    selected = _select(io, io.inventory())
    if selected is None:
        return RunResult(rid, RunPhase.SELECT, "IDLE", reason="NO_ACTIONABLE_ITEM")

    item, state = selected
    item_id = _item_id(item)
    operation = _operation_for(state, item)
    assert operation is not None

    if operation == "merge_expected_head" and not merge_ok(item)[0]:
        return RunResult(rid, RunPhase.RECONCILE_ITEM, "BLOCKED", action=operation, item_id=item_id, reason="MERGE_OK_FALSE")

    observed = io.observe_item(item)
    key = _lease_key_for(repo_id, item_id, operation, item)
    lease = acquire(store, key, rid, observed, now_srv=now_srv)
    if lease is None:
        return RunResult(rid, RunPhase.ACQUIRE_CAS_LEASE, "WAIT", action=operation, item_id=item_id, reason="LEASE_BUSY")

    observed_now = io.observe_item(item)
    if observed_now != observed:
        return RunResult(rid, RunPhase.RECONCILE_ITEM, "WAIT", action=operation, item_id=item_id, reason="OBSERVATION_CHANGED")

    with_intent = attach_intent(store, lease, repo_id, item_id, _intent_operation(operation), now_srv=now_srv)
    if with_intent is None:
        return RunResult(rid, RunPhase.WRITE_INTENT, "WAIT", action=operation, item_id=item_id, reason="INTENT_CAS_FAILED")

    observed_final = io.observe_item(item)
    ok, fence_reason = fence_ok(store, repo_id, with_intent, observed_final, now_srv=now_srv)
    if not ok:
        return RunResult(rid, RunPhase.FENCE_CHECK, "BLOCKED", action=operation, item_id=item_id, reason=fence_reason)

    mutation = io.execute_guarded(operation, item, with_intent)
    status = mutation.get("status") if isinstance(mutation, Mapping) else None
    if status in {"COMPLETE", "REPLAY_NOOP"}:
        resolved = resolve_intent(store, with_intent, "DONE")
        if resolved is None:
            return RunResult(rid, RunPhase.ACTION, "WAIT", action=operation, item_id=item_id, reason="RESULT_COMMIT_CAS_FAILED", mutation_result=mutation)
        return RunResult(rid, RunPhase.EXIT, "COMPLETE", action=operation, item_id=item_id, mutation_result=mutation)
    if status in {"FAILED", "BLOCKED"}:
        resolved = resolve_intent(store, with_intent, "ABORTED")
        if resolved is None:
            return RunResult(rid, RunPhase.ACTION, "WAIT", action=operation, item_id=item_id, reason="ABORT_COMMIT_CAS_FAILED", mutation_result=mutation)
        return RunResult(rid, RunPhase.EXIT, status, action=operation, item_id=item_id, mutation_result=mutation)

    return RunResult(rid, RunPhase.ACTION, "WAIT", action=operation, item_id=item_id, reason="OUTCOME_UNKNOWN", mutation_result=mutation)


class GuardedWriteBridge:
    """Bridge controller actions into the existing certified write adapter."""

    def __init__(self, client: Any, token_store: Any):
        self.client = client
        self.token_store = token_store

    def execute(self, operation: str, item: Mapping[str, Any], lease: Lease) -> Mapping[str, Any]:
        """Reproduce authorization and delegate to ``execute_mutation``."""
        from l5_activation import authorize_mutation
        from l5_write_adapter import execute_mutation

        snapshot = item.get("activation_snapshot")
        if not isinstance(snapshot, dict):
            return {"status": "BLOCKED", "reason": "ACTIVATION_SNAPSHOT_MISSING"}
        auth = authorize_mutation(snapshot)
        expected = {
            "retry_ci": "retry_ci",
            "dispatch_review": "dispatch_review",
            "remediate_review": "remediate_review",
            "merge_expected_head": "merge_expected_head",
            "reserve_next_wu": "reserve_next_wu",
        }.get(operation)
        if expected is None or auth.get("mutation") != expected:
            return {"status": "BLOCKED", "reason": "ACTION_AUTHORIZATION_MISMATCH"}
        if lease.intent is None:
            return {"status": "BLOCKED", "reason": "LEASE_INTENT_MISSING"}
        if auth.get("expected_head_sha") != lease.intent.expected_head:
            return {"status": "BLOCKED", "reason": "LEASE_HEAD_MISMATCH"}
        if auth.get("expected_base_sha") != lease.intent.expected_base:
            return {"status": "BLOCKED", "reason": "LEASE_BASE_MISMATCH"}
        return execute_mutation(auth, snapshot, self.client, self.token_store)
