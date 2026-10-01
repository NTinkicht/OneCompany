#!/usr/bin/env python3
"""Executable Claude-exact L5 BOOT-to-ACTION controller.

The runner reconstructs repository truth every invocation, recovers orphaned
intents before selecting work, acquires one lease, re-observes the resource,
writes one intent, revalidates the complete authorization predicate at the
final write boundary, and delegates the effect to the existing guarded write
adapter. Main-changing operations retain a durable repository merge lock until
post-merge health verification completes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from l5_kernel import (
    Budget,
    CASStore,
    HUMAN_CLEAR_ONLY,
    ItemState,
    Lease,
    Observation,
    RepoMode,
    acquire,
    attach_intent,
    capacity_slot_key,
    classify_item,
    fence_ok,
    governance_mode,
    idem_key,
    intent_recovery,
    intent_restraint_status,
    lease_key,
    merge_ok,
    merge_ok_v11,
    merge_precheck_v11,
    new_run_id,
    release,
    repo_merge_lock_key,
    resolve_intent,
    verify_intent,
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
    POST_MERGE_VERIFY = "POST_MERGE_VERIFY"
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
    """Trusted structured evidence/action boundary required by the runner."""

    def repo_snapshot(self) -> Mapping[str, Any]: ...
    def pending_intent_leases(self) -> Sequence[Lease]: ...
    def detect_intent_effect(self, lease: Lease) -> str: ...
    def inventory(self) -> Sequence[Mapping[str, Any]]: ...
    def refresh_item(self, item: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def budget_for(self, item: Mapping[str, Any]) -> Budget: ...
    def observe_item(self, item: Mapping[str, Any]) -> Observation: ...
    def trusted_now(self) -> float: ...
    def post_merge_health(self, item: Mapping[str, Any]) -> str: ...
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


def _trusted_now(io: ControllerIO) -> float:
    """Read fresh trusted/server time and fail closed on malformed values."""
    value = io.trusted_now()
    if not isinstance(value, (int, float)):
        raise ValueError("L5_TRUSTED_TIME_INVALID")
    return float(value)


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
        ItemState.INTENT_RESTRAINT_FAILED: 7,
        ItemState.INTENT_RESTRAINT_PENDING: 8,
        ItemState.MERGE_ELIGIBLE: 9,
        ItemState.IMPLEMENT: 10,
        ItemState.IDLE: 11,
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
    # MAIN_BROKEN requires its own independently authorized recovery path.
    # Do not repeatedly select an operation the guarded bridge cannot authorize.
    if state == ItemState.IDLE and item.get("replenish_candidate") is True:
        return "reserve_next_wu"
    return None


def _lease_key_for(
    repo_id: str,
    item_id: str,
    operation: str,
    item: Mapping[str, Any],
) -> str:
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


def _sync_mode(store: CASStore, repo_id: str, derived: RepoMode) -> tuple[bool, str]:
    """Persist derived mode without auto-clearing protected modes."""
    current, version = store.read_repo_mode(repo_id)
    if current == derived:
        return True, "UNCHANGED"
    if current in HUMAN_CLEAR_ONLY:
        return False, "HUMAN_CLEAR_REQUIRED"
    if current == RepoMode.MERGE_LOCKED:
        return False, "POST_MERGE_VERIFICATION_REQUIRED"
    if not store.cas_repo_mode(repo_id, version, derived):
        return False, "MODE_CAS_CONFLICT"
    return True, "UPDATED"


def _recover_pending(io: ControllerIO, store: CASStore) -> tuple[bool, str]:
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


def _select(
    repo_id: str,
    io: ControllerIO,
    store: CASStore,
    items: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ItemState] | None:
    """Classify and select one actionable item, skipping active cooldown leases."""
    candidates: list[tuple[int, str, Mapping[str, Any], ItemState]] = []
    now = _trusted_now(io)
    for raw in items:
        item = dict(raw)
        item["l5_intent_restraint_required"] = True
        state = classify_item(item, io.budget_for(item))
        operation = _operation_for(state, item)
        if operation is None:
            continue
        key = _lease_key_for(repo_id, _item_id(item), operation, item)
        current = store.read(key)
        if current is not None and (
            current.expires_at > now
            or (current.intent is not None and current.intent.state == "PENDING")
        ):
            continue
        candidates.append((_state_priority(state), _item_id(item), item, state))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1]))
    _, _, item, state = candidates[0]
    return item, state


def _find_merged_unverified(
    repo_id: str,
    lock: Lease,
    io: ControllerIO,
    items: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Return the merged-unverified item bound to the durable merge intent."""
    if lock.intent is None or lock.intent.operation not in {"merge", "revert"}:
        return None
    found = []
    for item in items:
        if classify_item(item, io.budget_for(item)) != ItemState.MERGED_UNVERIFIED:
            continue
        item_id = _item_id(item)
        bound = idem_key(
            repo_id,
            item_id,
            lock.intent.expected_head,
            lock.intent.expected_base,
            lock.intent.operation,
        )
        if bound == lock.intent.idem_key:
            found.append(item)
    return found[0] if len(found) == 1 else None


def _post_merge_verify(
    repo_id: str,
    io: ControllerIO,
    store: CASStore,
    items: Sequence[Mapping[str, Any]],
    rid: str,
) -> RunResult:
    """Keep MERGE_LOCKED until trusted post-merge health is terminal."""
    lock_key = repo_merge_lock_key(repo_id)
    lock = store.read(lock_key)
    if (
        lock is None
        or lock.intent is None
        or lock.intent.state not in {"DONE", "VERIFIED"}
        or lock.intent.operation not in {"merge", "revert"}
    ):
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            reason="MERGE_LOCK_EVIDENCE_INVALID",
        )

    item = _find_merged_unverified(repo_id, lock, io, items)
    if item is None:
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            reason="MERGE_LOCK_RECONCILIATION_REQUIRED",
        )

    item_id = _item_id(item)
    if (
        lock.intent.idem_key
        != idem_key(
            repo_id,
            item_id,
            lock.intent.expected_head,
            lock.intent.expected_base,
            lock.intent.operation,
        )
    ):
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            item_id=item_id,
            reason="MERGE_LOCK_EVIDENCE_INVALID",
        )

    refreshed = io.refresh_item(item)
    if _item_id(refreshed) != item_id:
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "BLOCKED",
            item_id=item_id,
            reason="ITEM_ID_CHANGED",
        )

    health = io.post_merge_health(refreshed)
    if health == "UNKNOWN":
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            item_id=item_id,
            reason="POST_MERGE_HEALTH_UNKNOWN",
        )
    if health not in {"HEALTHY", "BROKEN", "ENV_BROKEN"}:
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "BLOCKED",
            item_id=item_id,
            reason="POST_MERGE_HEALTH_INVALID",
        )

    if lock.intent.state == "DONE":
        verified = verify_intent(store, lock)
        if verified is None:
            return RunResult(
                rid,
                RunPhase.POST_MERGE_VERIFY,
                "WAIT",
                item_id=item_id,
                reason="POST_MERGE_VERIFY_CAS_FAILED",
            )
        lock = verified

    release_now = _trusted_now(io)
    released = release(store, lock, now_srv=release_now)
    if released is None:
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            item_id=item_id,
            reason="MERGE_LOCK_RELEASE_CAS_FAILED",
        )

    current_mode, mode_version = store.read_repo_mode(repo_id)
    if current_mode != RepoMode.MERGE_LOCKED:
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "BLOCKED",
            item_id=item_id,
            reason="MERGE_LOCK_MODE_LOST",
        )

    target_mode = {
        "HEALTHY": RepoMode.NORMAL,
        "BROKEN": RepoMode.MAIN_BROKEN,
        "ENV_BROKEN": RepoMode.MAIN_BROKEN_ENV,
    }[health]
    if not store.cas_repo_mode(
        repo_id,
        mode_version,
        target_mode,
        post_merge_verified=True,
    ):
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            item_id=item_id,
            reason="POST_MERGE_MODE_CAS_FAILED",
        )

    if health == "HEALTHY":
        return RunResult(
            rid,
            RunPhase.EXIT,
            "COMPLETE",
            action="verify_post_merge",
            item_id=item_id,
            reason="POST_MERGE_VERIFIED",
        )
    if health == "BROKEN":
        return RunResult(
            rid,
            RunPhase.EXIT,
            "WAIT",
            action="verify_post_merge",
            item_id=item_id,
            reason="MAIN_BROKEN",
        )
    return RunResult(
        rid,
        RunPhase.EXIT,
        "WAIT",
        action="verify_post_merge",
        item_id=item_id,
        reason="MAIN_BROKEN_ENV",
    )


def _revalidate_before_write(
    repo_id: str,
    io: ControllerIO,
    store: CASStore,
    operation: str,
    original: Mapping[str, Any],
    expected_observation: Observation,
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Refresh complete evidence immediately before a material write."""
    fresh_repo = io.repo_snapshot()
    derived = governance_mode(fresh_repo)
    current_mode, _ = store.read_repo_mode(repo_id)
    allowed_mode = RepoMode.MAIN_BROKEN if operation == "revert" else RepoMode.NORMAL
    if derived != allowed_mode or current_mode != allowed_mode:
        return None, f"REPO_MODE_{derived.value}"

    fresh = dict(io.refresh_item(original))
    fresh["l5_intent_restraint_required"] = True
    if _item_id(fresh) != _item_id(original):
        return None, "ITEM_ID_CHANGED"
    if io.observe_item(fresh) != expected_observation:
        return None, "OBSERVATION_CHANGED"
    if operation == "merge_expected_head" and not merge_precheck_v11(fresh)[0]:
        return None, "MERGE_OK_FALSE_FINAL"
    return fresh, None


def _terminalize_non_main_write(
    io: ControllerIO,
    store: CASStore,
    lease: Lease,
    *,
    state: str,
) -> tuple[bool, str]:
    """Resolve and release a non-main-changing operation."""
    resolved = resolve_intent(store, lease, state)
    if resolved is None:
        return False, "RESULT_COMMIT_CAS_FAILED"
    if release(store, resolved, now_srv=_trusted_now(io)) is None:
        return False, "LEASE_RELEASE_CAS_FAILED"
    return True, "TERMINAL"


def _enter_merge_locked(
    repo_id: str,
    store: CASStore,
    lease: Lease,
) -> tuple[bool, str]:
    """Resolve a successful main write and durably freeze further merges."""
    resolved = resolve_intent(store, lease, "DONE")
    if resolved is None:
        return False, "RESULT_COMMIT_CAS_FAILED"
    current_mode, mode_version = store.read_repo_mode(repo_id)
    expected = RepoMode.MAIN_BROKEN if lease.intent and lease.intent.operation == "revert" else RepoMode.NORMAL
    if current_mode != expected:
        return False, "REPO_MODE_CHANGED_AFTER_WRITE"
    if not store.cas_repo_mode(repo_id, mode_version, RepoMode.MERGE_LOCKED):
        return False, "MERGE_LOCK_MODE_CAS_FAILED"
    return True, "MERGED_UNVERIFIED"


def run_once(
    repo_id: str,
    io: ControllerIO,
    store: CASStore,
    *,
    now_srv: float | None = None,
    run_id: str | None = None,
) -> RunResult:
    """Execute one deterministic BOOT-to-ACTION controller invocation."""
    del now_srv  # Compatibility only. All write timing uses fresh trusted time.
    rid = run_id or new_run_id()
    repo = io.repo_snapshot()

    if repo.get("halted") is True:
        return RunResult(rid, RunPhase.HALT_CHECK, "BLOCKED", reason="HALTED")

    derived = governance_mode(repo)
    current_mode, _ = store.read_repo_mode(repo_id)

    if derived in HUMAN_CLEAR_ONLY:
        if current_mode != derived:
            _, version = store.read_repo_mode(repo_id)
            if current_mode not in HUMAN_CLEAR_ONLY and current_mode != RepoMode.MERGE_LOCKED:
                store.cas_repo_mode(repo_id, version, derived)
        return RunResult(
            rid,
            RunPhase.REPOSITORY_MODE,
            "BLOCKED",
            reason=derived.value,
        )

    recovered, recovery_reason = _recover_pending(io, store)
    if not recovered:
        return RunResult(
            rid,
            RunPhase.INTENT_RECOVERY,
            "WAIT",
            reason=recovery_reason,
        )

    items = list(io.inventory())

    current_mode, _ = store.read_repo_mode(repo_id)
    if current_mode == RepoMode.MERGE_LOCKED:
        return _post_merge_verify(repo_id, io, store, items, rid)

    synced, sync_reason = _sync_mode(store, repo_id, derived)
    if not synced:
        return RunResult(
            rid,
            RunPhase.REPOSITORY_MODE,
            "BLOCKED",
            reason=sync_reason,
        )
    if derived not in {RepoMode.NORMAL, RepoMode.MAIN_BROKEN}:
        return RunResult(
            rid,
            RunPhase.REPOSITORY_MODE,
            "WAIT",
            reason=derived.value,
        )

    selected = _select(repo_id, io, store, items)
    if selected is None:
        return RunResult(
            rid,
            RunPhase.SELECT,
            "IDLE",
            reason="NO_ACTIONABLE_ITEM",
        )

    item, state = selected
    item_id = _item_id(item)
    operation = _operation_for(state, item)
    assert operation is not None

    if operation == "merge_expected_head" and not merge_precheck_v11(item)[0]:
        return RunResult(
            rid,
            RunPhase.RECONCILE_ITEM,
            "BLOCKED",
            action=operation,
            item_id=item_id,
            reason="MERGE_OK_FALSE",
        )

    observed = io.observe_item(item)
    key = _lease_key_for(repo_id, item_id, operation, item)
    lease = acquire(
        store,
        key,
        rid,
        observed,
        now_srv=_trusted_now(io),
    )
    if lease is None:
        return RunResult(
            rid,
            RunPhase.ACQUIRE_CAS_LEASE,
            "WAIT",
            action=operation,
            item_id=item_id,
            reason="LEASE_BUSY",
        )

    fresh, reason = _revalidate_before_write(
        repo_id,
        io,
        store,
        operation,
        item,
        observed,
    )
    if fresh is None:
        return RunResult(
            rid,
            RunPhase.RECONCILE_ITEM,
            "WAIT",
            action=operation,
            item_id=item_id,
            reason=reason,
        )

    with_intent = attach_intent(
        store,
        lease,
        repo_id,
        item_id,
        _intent_operation(operation),
        now_srv=_trusted_now(io),
    )
    if with_intent is None:
        return RunResult(
            rid,
            RunPhase.WRITE_INTENT,
            "WAIT",
            action=operation,
            item_id=item_id,
            reason="INTENT_CAS_FAILED",
        )

    final_item, reason = _revalidate_before_write(
        repo_id,
        io,
        store,
        operation,
        fresh,
        observed,
    )
    if final_item is None:
        if resolve_intent(store, with_intent, "ABORTED") is None:
            return RunResult(rid, RunPhase.FENCE_CHECK, "WAIT", action=operation, item_id=item_id, reason="INTENT_ABORT_CAS_FAILED")
        return RunResult(
            rid,
            RunPhase.FENCE_CHECK,
            "BLOCKED",
            action=operation,
            item_id=item_id,
            reason=reason,
        )

    observed_final = io.observe_item(final_item)
    fence_now = _trusted_now(io)
    ok, fence_reason = fence_ok(
        store,
        repo_id,
        with_intent,
        observed_final,
        now_srv=fence_now,
    )
    if not ok:
        if fence_reason not in {"LEASE_LOST", "LEASE_MISSING"}:
            resolve_intent(store, with_intent, "ABORTED")
        return RunResult(
            rid,
            RunPhase.FENCE_CHECK,
            "BLOCKED",
            action=operation,
            item_id=item_id,
            reason=fence_reason,
        )

    if operation == "merge_expected_head":
        final_merge = dict(io.refresh_item(final_item))
        final_merge["l5_intent_restraint_required"] = True
        if _item_id(final_merge) != item_id or io.observe_item(final_merge) != observed:
            resolve_intent(store, with_intent, "ABORTED")
            return RunResult(rid, RunPhase.FENCE_CHECK, "BLOCKED", action=operation, item_id=item_id, reason="OBSERVATION_CHANGED")
        final_repo = io.repo_snapshot()
        final_mode, _ = store.read_repo_mode(repo_id)
        final_merge["merge_lock_owned"] = True
        final_merge["fence_ok"] = True
        final_merge["unresolved_other_intent"] = False
        final_merge["repo_mode"] = final_mode.value
        if governance_mode(final_repo) != RepoMode.NORMAL or not merge_ok_v11(final_merge)[0]:
            resolve_intent(store, with_intent, "ABORTED")
            return RunResult(rid, RunPhase.FENCE_CHECK, "BLOCKED", action=operation, item_id=item_id, reason="MERGE_OK_FALSE_FINAL")
        final_item = final_merge

    mutation = io.execute_guarded(operation, final_item, with_intent)
    status = mutation.get("status") if isinstance(mutation, Mapping) else None
    result_reason = mutation.get("reason") if isinstance(mutation, Mapping) else None

    effect_complete = status == "COMPLETE" or (
        status == "REPLAY_NOOP" and result_reason == "ALREADY_COMPLETE"
    )
    replay_pending = status == "REPLAY_NOOP" and result_reason in {
        "TOKEN_ALREADY_PERSISTED",
        "EFFECT_NOT_YET_VERIFIED",
    }

    if replay_pending:
        return RunResult(
            rid,
            RunPhase.ACTION,
            "WAIT",
            action=operation,
            item_id=item_id,
            reason="OUTCOME_UNKNOWN",
            mutation_result=mutation,
        )

    if effect_complete:
        if operation in {"merge_expected_head", "revert"}:
            transitioned, transition_reason = _enter_merge_locked(
                repo_id,
                store,
                with_intent,
            )
            if not transitioned:
                return RunResult(
                    rid,
                    RunPhase.ACTION,
                    "WAIT",
                    action=operation,
                    item_id=item_id,
                    reason=transition_reason,
                    mutation_result=mutation,
                )
            return RunResult(
                rid,
                RunPhase.EXIT,
                "WAIT",
                action=operation,
                item_id=item_id,
                reason="MERGED_UNVERIFIED",
                mutation_result=mutation,
            )

        terminal, terminal_reason = _terminalize_non_main_write(
            io,
            store,
            with_intent,
            state="DONE",
        )
        if not terminal:
            return RunResult(
                rid,
                RunPhase.ACTION,
                "WAIT",
                action=operation,
                item_id=item_id,
                reason=terminal_reason,
                mutation_result=mutation,
            )
        return RunResult(
            rid,
            RunPhase.EXIT,
            "COMPLETE",
            action=operation,
            item_id=item_id,
            mutation_result=mutation,
        )

    if status == "BLOCKED":
        # Abort the no-write intent but deliberately retain the live lease as
        # a bounded cooldown. _select skips active leases, so one bad item
        # cannot starve lower-priority work on subsequent invocations.
        if resolve_intent(store, with_intent, "ABORTED") is None:
            return RunResult(rid, RunPhase.ACTION, "WAIT", action=operation, item_id=item_id, reason="INTENT_ABORT_CAS_FAILED", mutation_result=mutation)
        return RunResult(rid, RunPhase.EXIT, "BLOCKED", action=operation, item_id=item_id, reason=result_reason or "ACTION_BLOCKED_COOLDOWN", mutation_result=mutation)

    if status == "FAILED":
        terminal, terminal_reason = _terminalize_non_main_write(
            io, store, with_intent, state="ABORTED"
        )
        if not terminal:
            return RunResult(rid, RunPhase.ACTION, "WAIT", action=operation, item_id=item_id, reason=terminal_reason, mutation_result=mutation)
        return RunResult(rid, RunPhase.EXIT, status, action=operation, item_id=item_id, mutation_result=mutation)

    return RunResult(
        rid,
        RunPhase.ACTION,
        "WAIT",
        action=operation,
        item_id=item_id,
        reason="OUTCOME_UNKNOWN",
        mutation_result=mutation,
    )


class GuardedWriteBridge:
    """Bridge controller actions into the existing certified write adapter."""

    def __init__(self, client: Any, token_store: Any):
        """Store credential-bearing client and durable token store references."""
        self.client = client
        self.token_store = token_store

    def execute_guarded(
        self,
        operation: str,
        item: Mapping[str, Any],
        lease: Lease,
    ) -> Mapping[str, Any]:
        """Reproduce authorization and delegate to ``execute_mutation``."""
        from l5_activation import authorize_mutation
        from l5_write_adapter import execute_mutation

        snapshot = item.get("activation_snapshot")
        if not isinstance(snapshot, dict):
            return {"status": "BLOCKED", "reason": "ACTIVATION_SNAPSHOT_MISSING"}

        try:
            auth = authorize_mutation(snapshot)
        except ValueError as exc:
            return {
                "status": "BLOCKED",
                "reason": f"AUTHORIZATION_INVALID:{exc}",
            }
        expected = {
            "retry_ci": "retry_ci",
            "dispatch_review": "dispatch_review",
            "remediate_review": "remediate_review",
            "update_branch": "update_branch",
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
