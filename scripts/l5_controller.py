#!/usr/bin/env python3
"""Executable Claude L5 BOOT-to-ACTION controller.

The runner is deterministic and credential-free. Trusted adapters supply live
evidence, durable CAS state, outcome detection, and the already-hardened write
sink. A run never waits; it performs at most one material action then exits.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol

from l5_kernel import (
    Budget,
    CASStore,
    HUMAN_CLEAR_ONLY,
    ItemState,
    Observation,
    RepoMode,
    acquire,
    attach_intent,
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


class RunStage(str, Enum):
    """Deterministic controller stages."""

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


@dataclass(frozen=True)
class RunResult:
    """One controller invocation result."""

    run_id: str
    stage: RunStage
    status: str
    item_id: str | None = None
    state: str | None = None
    action: str | None = None
    reason: str | None = None


class ControllerPorts(Protocol):
    """Trusted runtime boundary used by the deterministic runner."""

    def governance_snapshot(self) -> Mapping[str, Any]: ...
    def inventory(self) -> list[Mapping[str, Any]]: ...
    def observe_item(self, item_id: str) -> Mapping[str, Any]: ...
    def budget_for(self, item_id: str) -> Budget: ...
    def detect_intent(self, intent: Any) -> str: ...
    def perform(
        self,
        operation: str,
        item: Mapping[str, Any],
        *,
        expected_head: str,
        expected_base: str,
        idempotency_key: str,
    ) -> str: ...
    def post_merge_health(self, item_id: str) -> str: ...


_PRIORITY = {
    ItemState.MERGED_UNVERIFIED: 0,
    ItemState.MERGE_OUTCOME_UNKNOWN: 1,
    ItemState.MAIN_BROKEN: 2,
    ItemState.CI_RED_DETERMINISTIC: 3,
    ItemState.FINDINGS_OPEN: 4,
    ItemState.BEHIND_BASE: 5,
    ItemState.CI_RED_INFRA: 6,
    ItemState.CI_GREEN_UNREVIEWED: 7,
    ItemState.MERGE_ELIGIBLE: 8,
    ItemState.IMPLEMENT: 9,
    ItemState.IDLE: 99,
}


def _item_id(item: Mapping[str, Any]) -> str:
    """Return a stable item identity or fail closed."""
    value = item.get("item_id")
    if not isinstance(value, str) or not value:
        raise ValueError("ITEM_ID_MISSING")
    return value


def _observation(item: Mapping[str, Any]) -> Observation:
    """Build a write-fence observation from fresh item evidence."""
    head = item.get("head_sha")
    base = item.get("base_sha")
    if not isinstance(head, str) or not isinstance(base, str):
        raise ValueError("ITEM_REFS_UNKNOWN")
    return Observation(
        head=head,
        base=base,
        wu_body_hash=str(item.get("wu_body_hash", "")),
        pr_updated_at=str(item.get("pr_updated_at", "")),
    )


def _select(classified: list[tuple[Mapping[str, Any], ItemState]]) -> tuple[Mapping[str, Any], ItemState] | None:
    """Select deterministically by state priority then item ID."""
    waiting = {
        ItemState.WAIT_CI,
        ItemState.CI_MISSING,
        ItemState.WAIT_PROVIDER,
        ItemState.WAIT_DEPENDENCY,
        ItemState.BLOCK_HUMAN,
        ItemState.GOVERNANCE_CHANGE,
        ItemState.DISPUTED_FINDING,
        ItemState.PARKED,
        ItemState.MERGED_VERIFIED,
        ItemState.SUPERSEDED,
        ItemState.MERGE_QUEUED,
    }
    actionable = [row for row in classified if row[1] not in waiting]
    if not actionable:
        return None
    return min(actionable, key=lambda row: (_PRIORITY.get(row[1], 50), _item_id(row[0])))


def _recover_pending_intents(store: CASStore, ports: ControllerPorts) -> tuple[str | None, str | None]:
    """Resolve pending intents before new work; unknown outcomes block replay."""
    for lease in sorted(store.list_leases(), key=lambda row: row.key):
        if not lease.active or lease.intent is None or lease.intent.state != "PENDING":
            continue
        decision = intent_recovery(lease, ports.detect_intent(lease.intent))
        if decision == "READBACK_REQUIRED":
            return "BLOCKED", f"OUTCOME_UNKNOWN:{lease.key}"
        terminal = "DONE" if decision == "RESOLVE_DONE" else "ABORTED"
        if resolve_intent(store, lease, terminal) is None:
            return "BLOCKED", f"INTENT_CAS_CONFLICT:{lease.key}"
    return None, None


def _operation_for(state: ItemState) -> str | None:
    """Map derived state to one permitted one-shot operation."""
    return {
        ItemState.CI_RED_INFRA: "ci_rerun",
        ItemState.CI_GREEN_UNREVIEWED: "review_request",
        ItemState.BEHIND_BASE: "update_branch",
        ItemState.MERGE_ELIGIBLE: "merge",
    }.get(state)


def run_once(
    repo_id: str,
    store: CASStore,
    ports: ControllerPorts,
    *,
    now_srv: float,
    run_id: str | None = None,
) -> RunResult:
    """Execute one BOOT-to-ACTION pass and at most one material mutation."""
    rid = run_id or new_run_id()

    governance = ports.governance_snapshot()
    mode = governance_mode(governance)
    current_mode, mode_version = store.read_repo_mode(repo_id)
    if current_mode != mode:
        if current_mode in HUMAN_CLEAR_ONLY:
            return RunResult(
                rid,
                RunStage.REPOSITORY_MODE,
                "BLOCKED",
                reason=f"HUMAN_CLEAR_REQUIRED:{current_mode.value}",
            )
        if not store.cas_repo_mode(repo_id, mode_version, mode):
            return RunResult(rid, RunStage.REPOSITORY_MODE, "BLOCKED", reason="MODE_CAS_CONFLICT")
    if mode != RepoMode.NORMAL:
        return RunResult(rid, RunStage.REPOSITORY_MODE, "BLOCKED", reason=f"REPO_MODE_{mode.value}")

    recovery_status, recovery_reason = _recover_pending_intents(store, ports)
    if recovery_status is not None:
        return RunResult(rid, RunStage.INTENT_RECOVERY, recovery_status, reason=recovery_reason)

    classified: list[tuple[Mapping[str, Any], ItemState]] = []
    for item in ports.inventory():
        item_id = _item_id(item)
        classified.append((item, classify_item(item, ports.budget_for(item_id))))
    selected = _select(classified)
    if selected is None:
        return RunResult(rid, RunStage.SELECT, "QUIESCENT", state="IDLE")

    item, state = selected
    item_id = _item_id(item)
    if state in {ItemState.CI_RED_DETERMINISTIC, ItemState.FINDINGS_OPEN, ItemState.IMPLEMENT}:
        return RunResult(rid, RunStage.ACTION, "NEEDS_IMPLEMENTATION", item_id=item_id, state=state.value)
    if state == ItemState.MAIN_BROKEN:
        return RunResult(
            rid,
            RunStage.ACTION,
            "BLOCKED",
            item_id=item_id,
            state=state.value,
            reason="REVERT_REQUIRES_HUMAN_AUTHORITY",
        )
    if state == ItemState.MERGED_UNVERIFIED:
        health = ports.post_merge_health(item_id)
        if health == "HEALTHY":
            return RunResult(rid, RunStage.ACTION, "VERIFIED", item_id=item_id, state=ItemState.MERGED_VERIFIED.value)
        if health == "BROKEN":
            _, version = store.read_repo_mode(repo_id)
            store.cas_repo_mode(repo_id, version, RepoMode.MAIN_BROKEN)
            return RunResult(
                rid,
                RunStage.ACTION,
                "BLOCKED",
                item_id=item_id,
                state=ItemState.MAIN_BROKEN.value,
                reason="POST_MERGE_MAIN_BROKEN",
            )
        return RunResult(
            rid,
            RunStage.ACTION,
            "WAIT",
            item_id=item_id,
            state=state.value,
            reason="POST_MERGE_HEALTH_UNKNOWN",
        )

    fresh = ports.observe_item(item_id)
    fresh_state = classify_item(fresh, ports.budget_for(item_id))
    if fresh_state != state:
        return RunResult(
            rid,
            RunStage.RECONCILE_ITEM,
            "RECONCILE",
            item_id=item_id,
            state=fresh_state.value,
            reason="STATE_CHANGED",
        )

    operation = _operation_for(state)
    if operation is None:
        return RunResult(rid, RunStage.ACTION, "WAIT", item_id=item_id, state=state.value)

    observation = _observation(fresh)
    key = repo_merge_lock_key(repo_id) if operation == "merge" else lease_key(repo_id, "item", item_id, operation.upper())
    lease = acquire(store, key, rid, observation, now_srv=now_srv)
    if lease is None:
        return RunResult(
            rid,
            RunStage.ACQUIRE_CAS_LEASE,
            "WAIT",
            item_id=item_id,
            state=state.value,
            action=operation,
            reason="LEASE_BUSY",
        )

    intended = attach_intent(store, lease, repo_id, item_id, operation)
    if intended is None:
        return RunResult(
            rid,
            RunStage.WRITE_INTENT,
            "BLOCKED",
            item_id=item_id,
            state=state.value,
            action=operation,
            reason="INTENT_CAS_CONFLICT",
        )

    if operation == "merge":
        ok, failures = merge_ok(fresh)
        if not ok:
            resolve_intent(store, intended, "ABORTED")
            return RunResult(
                rid,
                RunStage.FENCE_CHECK,
                "BLOCKED",
                item_id=item_id,
                state=state.value,
                action=operation,
                reason="MERGE_OK:" + ",".join(failures),
            )

    observed_now = _observation(ports.observe_item(item_id))
    fenced, reason = fence_ok(store, repo_id, intended, observed_now, now_srv=now_srv)
    if not fenced:
        resolve_intent(store, intended, "ABORTED")
        return RunResult(
            rid,
            RunStage.FENCE_CHECK,
            "BLOCKED",
            item_id=item_id,
            state=state.value,
            action=operation,
            reason=reason,
        )

    outcome = ports.perform(
        operation,
        fresh,
        expected_head=observation.head,
        expected_base=observation.base,
        idempotency_key=intended.intent.idem_key,
    )
    if outcome == "APPLIED":
        if resolve_intent(store, intended, "DONE") is None:
            return RunResult(
                rid,
                RunStage.ACTION,
                "BLOCKED",
                item_id=item_id,
                state=state.value,
                action=operation,
                reason="POST_WRITE_INTENT_CAS_CONFLICT",
            )
        return RunResult(rid, RunStage.ACTION, "APPLIED", item_id=item_id, state=state.value, action=operation)
    if outcome == "NOT_APPLIED":
        resolve_intent(store, intended, "ABORTED")
        return RunResult(
            rid,
            RunStage.ACTION,
            "FAILED",
            item_id=item_id,
            state=state.value,
            action=operation,
            reason="WRITE_REJECTED",
        )
    return RunResult(
        rid,
        RunStage.ACTION,
        "OUTCOME_UNKNOWN",
        item_id=item_id,
        state=state.value,
        action=operation,
        reason="READBACK_REQUIRED",
    )
