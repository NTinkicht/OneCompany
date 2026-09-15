#!/usr/bin/env python3
"""Execute an already-resolved dispatch without creating coordination authority.

This A3 layer binds execution to live readiness, zero-extra-spend policy and the
canonical implementation lease. It also provides an append-only local dispatch
journal for idempotency. The journal is execution evidence only; it never grants
lease, review, merge or budget authority.
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import hashlib
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from dispatch import resolve_dispatch
from lease_lifecycle import coordination_view
from onecompany_lib import (
    CONTROL,
    ROOT,
    emergency_stop_active,
    github_repo_from_config,
    github_repo_from_remote,
    load_json,
)

WRITE_CAPABILITIES = {"implementation", "ci_remediation"}
ATTENDED_MECHANISM_KINDS = {"interactive", "manual"}
ACTIVE_STATES = {"DISPATCH_CLAIMED", "DISPATCH_STARTED"}
LOCK_METADATA_NAME = "owner.json"
DEFAULT_STALE_LOCK_SECONDS = 30.0

Adapter = Callable[[dict[str, Any]], dict[str, Any]]


def utc_now() -> str:
    """Return a stable UTC timestamp for execution evidence."""
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def dispatch_journal_path() -> Path:
    """Return the untracked local dispatch evidence path."""
    return ROOT / ".git" / "onecompany" / "dispatch-events.jsonl"


def load_dispatch_events(path: Path | None = None) -> list[dict[str, Any]]:
    """Load append-only dispatch evidence and fail closed on corruption."""
    target = path or dispatch_journal_path()
    if not target.exists():
        return []
    events: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"dispatch journal is corrupt at line {number}: {exc}"
                ) from exc
            if not isinstance(event, dict):
                raise RuntimeError(
                    f"dispatch journal line {number} is not an object"
                )
            events.append(event)
    return events


def _lock_metadata_path(lock_dir: Path) -> Path:
    return lock_dir / LOCK_METADATA_NAME


def _write_lock_metadata(lock_dir: Path, owner_token: str) -> None:
    metadata = {
        "version": 1,
        "pid": os.getpid(),
        "acquired_at_epoch": time.time(),
        "owner_token": owner_token,
    }
    path = _lock_metadata_path(lock_dir)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(metadata, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_lock_metadata(lock_dir: Path) -> dict[str, Any] | None:
    path = _lock_metadata_path(lock_dir)
    try:
        with path.open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    pid = metadata.get("pid")
    acquired = metadata.get("acquired_at_epoch")
    token = metadata.get("owner_token")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(acquired, (int, float))
        or isinstance(acquired, bool)
        or not isinstance(token, str)
        or not token
    ):
        return None
    return metadata


def _pid_alive(pid: int) -> bool | None:
    """Return live/dead when demonstrable; None means the platform cannot prove it."""
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return None
    return True


def _reclaim_stale_lock(lock_dir: Path, stale_after_seconds: float) -> bool:
    """Reclaim only a valid, old lock whose recorded owner is provably dead."""
    metadata = _read_lock_metadata(lock_dir)
    if metadata is None:
        return False
    age = time.time() - float(metadata["acquired_at_epoch"])
    if age < stale_after_seconds:
        return False
    if _pid_alive(int(metadata["pid"])) is not False:
        return False

    marker = lock_dir / "reclaim.json"
    reclaim_token = str(uuid.uuid4())
    try:
        with marker.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(
                {
                    "pid": os.getpid(),
                    "owner_token": reclaim_token,
                    "created_at_epoch": time.time(),
                },
                handle,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except (FileExistsError, FileNotFoundError, OSError):
        return False

    try:
        if _read_lock_metadata(lock_dir) != metadata:
            return False
        if _pid_alive(int(metadata["pid"])) is not False:
            return False
        children = {item.name for item in lock_dir.iterdir()}
        if children != {LOCK_METADATA_NAME, marker.name}:
            return False
        _lock_metadata_path(lock_dir).unlink()
        marker.unlink()
        lock_dir.rmdir()
        return True
    except (FileNotFoundError, OSError):
        return False
    finally:
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


@contextmanager
def journal_lock(
    path: Path | None = None,
    timeout_seconds: float = 5.0,
    stale_after_seconds: float = DEFAULT_STALE_LOCK_SECONDS,
) -> Iterator[None]:
    """Acquire the journal lock, recovering only provably abandoned lock owners."""
    target = path or dispatch_journal_path()
    lock_dir = target.with_name(target.name + ".lock")
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    owner_token = str(uuid.uuid4())
    while True:
        try:
            lock_dir.mkdir()
            try:
                _write_lock_metadata(lock_dir, owner_token)
            except Exception:
                try:
                    _lock_metadata_path(lock_dir).unlink()
                except FileNotFoundError:
                    pass
                try:
                    lock_dir.rmdir()
                except OSError:
                    pass
                raise
            break
        except FileExistsError as exc:
            if time.monotonic() >= deadline:
                if _reclaim_stale_lock(lock_dir, stale_after_seconds):
                    deadline = time.monotonic() + timeout_seconds
                    continue
                raise RuntimeError("dispatch_journal_locked") from exc
            time.sleep(0.02)
    try:
        yield
    finally:
        metadata = _read_lock_metadata(lock_dir)
        if metadata and metadata.get("owner_token") == owner_token:
            try:
                _lock_metadata_path(lock_dir).unlink()
                lock_dir.rmdir()
            except FileNotFoundError:
                pass


def _append_event_unlocked(
    path: Path,
    *,
    dispatch_id: str,
    state: str,
    attempt_id: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one execution-evidence event while the journal lock is held."""
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "version": 1,
        "event_id": str(uuid.uuid4()),
        "dispatch_id": dispatch_id,
        "attempt_id": attempt_id,
        "state": state,
        "timestamp": utc_now(),
        "evidence": evidence or {},
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event


def dispatch_identity(
    *,
    repository: str,
    work_unit: str,
    actor: str,
    capability: str,
    mechanism_id: str,
    lease: dict[str, Any] | None,
) -> str:
    """Derive a deterministic identity for one canonical dispatch transition."""
    canonical = {
        "repository": repository,
        "work_unit": work_unit,
        "actor": actor,
        "capability": capability,
        "mechanism_id": mechanism_id,
        "lease_id": lease.get("id") if lease else None,
        "branch": lease.get("branch") if lease else None,
        "pr": lease.get("pr") if lease else None,
    }
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "dispatch-" + hashlib.sha256(encoded).hexdigest()


def validate_write_lease(
    view: dict[str, Any],
    *,
    lease_id: str | None,
    actor: str,
    work_unit: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Require the exact canonical active implementation lease for a write dispatch."""
    reasons: list[str] = []
    if not lease_id:
        return None, ["active_lease_id_required_for_write_dispatch"]
    lease = next(
        (
            item
            for item in view.get("active_leases", [])
            if item.get("id") == lease_id and item.get("role") == "implementation"
        ),
        None,
    )
    if lease is None:
        return None, ["lease_not_canonical_active_and_unexpired"]
    if lease.get("actor") != actor:
        reasons.append("lease_actor_mismatch")
    if lease.get("work_unit") != work_unit:
        reasons.append("lease_work_unit_mismatch")
    return lease, reasons


def repository_identity() -> tuple[str | None, list[str]]:
    """Bind execution evidence to the checkout identity and reject identity drift."""
    config = load_json(CONTROL / "config.json")
    configured = github_repo_from_config(config)
    remote = github_repo_from_remote()
    if remote and configured and remote != configured:
        return None, ["repository_identity_mismatch"]
    repository = remote or configured
    if not repository:
        return None, ["repository_identity_unavailable"]
    return repository, []


def _last_dispatch_event(
    events: list[dict[str, Any]], dispatch_id: str
) -> dict[str, Any] | None:
    matching = [event for event in events if event.get("dispatch_id") == dispatch_id]
    return matching[-1] if matching else None


def claim_dispatch(
    dispatch_id: str,
    *,
    journal_path: Path | None = None,
    retry_failed: bool = False,
) -> tuple[str, str | None, dict[str, Any] | None]:
    """Atomically claim one external start or return the existing canonical state."""
    target = journal_path or dispatch_journal_path()
    with journal_lock(target):
        events = load_dispatch_events(target)
        last = _last_dispatch_event(events, dispatch_id)
        if last:
            state = str(last.get("state") or "")
            if state in ACTIVE_STATES:
                return "DISPATCH_ALREADY_ACTIVE", None, last
            if state == "DISPATCH_COMPLETED":
                return "DISPATCH_COMPLETED", None, last
            if state == "DISPATCH_FAILED_SAFE" and not retry_failed:
                return "DISPATCH_FAILED_SAFE", None, last
        attempt_id = str(uuid.uuid4())
        event = _append_event_unlocked(
            target,
            dispatch_id=dispatch_id,
            state="DISPATCH_CLAIMED",
            attempt_id=attempt_id,
            evidence={"retry_failed": retry_failed},
        )
        return "DISPATCH_CLAIMED", attempt_id, event


def record_dispatch_outcome(
    dispatch_id: str,
    attempt_id: str,
    state: str,
    evidence: dict[str, Any],
    *,
    journal_path: Path | None = None,
) -> dict[str, Any]:
    """Append only a valid state transition for the exact active attempt."""
    if state not in {"DISPATCH_STARTED", "DISPATCH_COMPLETED", "DISPATCH_FAILED_SAFE"}:
        raise ValueError(f"unsupported dispatch outcome: {state}")
    target = journal_path or dispatch_journal_path()
    with journal_lock(target):
        last = _last_dispatch_event(load_dispatch_events(target), dispatch_id)
        if last is None:
            raise RuntimeError("dispatch_outcome_without_claim")
        if last.get("attempt_id") != attempt_id:
            raise RuntimeError("dispatch_outcome_attempt_mismatch")
        allowed = {
            "DISPATCH_CLAIMED": {"DISPATCH_STARTED", "DISPATCH_FAILED_SAFE"},
            "DISPATCH_STARTED": {"DISPATCH_COMPLETED", "DISPATCH_FAILED_SAFE"},
        }.get(str(last.get("state") or ""), set())
        if state not in allowed:
            raise RuntimeError("dispatch_outcome_invalid_transition")
        return _append_event_unlocked(
            target,
            dispatch_id=dispatch_id,
            state=state,
            attempt_id=attempt_id,
            evidence=evidence,
        )


def _outcome_unrecorded(
    dispatch_id: str,
    attempt_id: str,
    adapter_status: str,
    adapter_evidence: dict[str, Any],
    exc: Exception,
) -> dict[str, Any]:
    """Report journal failure without changing the active claim into retryable failure."""
    return {
        "status": "DISPATCH_OUTCOME_UNRECORDED",
        "dispatch_id": dispatch_id,
        "attempt_id": attempt_id,
        "adapter_status": adapter_status,
        "evidence": {
            "journal_error": str(exc),
            "adapter_evidence": adapter_evidence,
        },
    }


def execute_with_adapter(
    request: dict[str, Any],
    adapter: Adapter,
    *,
    journal_path: Path | None = None,
    retry_failed: bool = False,
) -> dict[str, Any]:
    """Run one injected automatic adapter with claim-before-side-effect semantics."""
    dispatch_id = str(request["dispatch_id"])
    state, attempt_id, existing = claim_dispatch(
        dispatch_id,
        journal_path=journal_path,
        retry_failed=retry_failed,
    )
    if state != "DISPATCH_CLAIMED":
        return {
            "status": state,
            "dispatch_id": dispatch_id,
            "existing_event": existing,
        }
    assert attempt_id is not None

    try:
        adapter_result = adapter(request)
        if not isinstance(adapter_result, dict):
            raise RuntimeError("adapter_result_not_object")
        outcome = str(adapter_result.get("status") or "")
        if outcome not in {"DISPATCH_STARTED", "DISPATCH_COMPLETED"}:
            raise RuntimeError("adapter_did_not_return_verified_start_or_completion")
    except Exception as exc:
        evidence = {"error": str(exc)}
        try:
            record_dispatch_outcome(
                dispatch_id,
                attempt_id,
                "DISPATCH_FAILED_SAFE",
                evidence,
                journal_path=journal_path,
            )
        except Exception as journal_exc:
            return _outcome_unrecorded(
                dispatch_id,
                attempt_id,
                "DISPATCH_FAILED_SAFE",
                evidence,
                journal_exc,
            )
        return {
            "status": "DISPATCH_FAILED_SAFE",
            "dispatch_id": dispatch_id,
            "attempt_id": attempt_id,
            "evidence": evidence,
        }

    adapter_evidence = adapter_result.get("evidence", {})
    try:
        if outcome == "DISPATCH_COMPLETED":
            record_dispatch_outcome(
                dispatch_id,
                attempt_id,
                "DISPATCH_STARTED",
                {
                    "adapter_reported_completion": True,
                    "adapter_evidence": adapter_evidence,
                },
                journal_path=journal_path,
            )
        record_dispatch_outcome(
            dispatch_id,
            attempt_id,
            outcome,
            adapter_evidence,
            journal_path=journal_path,
        )
    except Exception as exc:
        return _outcome_unrecorded(
            dispatch_id,
            attempt_id,
            outcome,
            adapter_evidence,
            exc,
        )
    return {
        "status": outcome,
        "dispatch_id": dispatch_id,
        "attempt_id": attempt_id,
        "evidence": adapter_evidence,
    }


def build_execution_request(
    args: argparse.Namespace,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Revalidate route, budget and lease immediately before an execution attempt."""
    resolution = resolve_dispatch(
        args.actor,
        args.capability,
        unattended=args.unattended,
        lease_id=args.lease_id,
    )
    if resolution.get("status") != "DISPATCH_READY":
        return None, resolution

    mechanism = next(
        (
            item
            for item in resolution.get("mechanisms", [])
            if item.get("id") == args.mechanism
        ),
        None,
    )
    reasons: list[str] = []
    if mechanism is None:
        reasons.append("selected_mechanism_not_dispatch_ready")

    actors = {
        item.get("id"): item
        for item in load_json(CONTROL / "actors.json").get("actors", [])
        if item.get("id")
    }
    actor = actors.get(args.actor, {})
    budget = load_json(CONTROL / "budget.json")
    allowed_classes = set(budget.get("cost_classes", {}).get("allowed", []))
    if actor.get("cost_class", "UNKNOWN_COST") not in allowed_classes:
        reasons.append("forbidden_by_zero_extra_spend_policy")

    if emergency_stop_active() and (
        args.unattended or args.capability in WRITE_CAPABILITIES
    ):
        reasons.append("emergency_stop_active")

    repository, repository_reasons = repository_identity()
    reasons.extend(repository_reasons)

    lease: dict[str, Any] | None = None
    if args.capability in WRITE_CAPABILITIES:
        try:
            view = coordination_view()
        except Exception as exc:
            reasons.append(f"coordination_unavailable:{exc}")
        else:
            lease, lease_reasons = validate_write_lease(
                view,
                lease_id=args.lease_id,
                actor=args.actor,
                work_unit=args.work_unit,
            )
            reasons.extend(lease_reasons)

    if args.capability == "merge_execution":
        reasons.append("merge_execution_requires_merge_gate_not_dispatch_executor")

    if reasons or mechanism is None or repository is None:
        return None, {
            "status": "CAPACITY_BLOCKED",
            "actor": args.actor,
            "capability": args.capability,
            "mechanism": args.mechanism,
            "work_unit": args.work_unit,
            "reasons": sorted(set(reasons)),
        }

    dispatch_id = dispatch_identity(
        repository=repository,
        work_unit=args.work_unit,
        actor=args.actor,
        capability=args.capability,
        mechanism_id=args.mechanism,
        lease=lease,
    )
    request = {
        "dispatch_id": dispatch_id,
        "repository": repository,
        "work_unit": args.work_unit,
        "actor": args.actor,
        "capability": args.capability,
        "mechanism": mechanism,
        "lease": lease,
        "unattended": args.unattended,
    }
    return request, {}


def main() -> int:
    """Resolve and execute a bounded dispatch, failing closed when no adapter exists."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--mechanism", required=True)
    parser.add_argument("--work-unit", required=True)
    parser.add_argument("--lease-id")
    parser.add_argument("--unattended", action="store_true")
    args = parser.parse_args()

    request, blocked = build_execution_request(args)
    if request is None:
        print(json.dumps(blocked, indent=2))
        return 2

    mechanism = request["mechanism"]
    kind = mechanism.get("kind")
    if kind in ATTENDED_MECHANISM_KINDS:
        payload = {
            "status": "DISPATCH_ATTENDED_REQUIRED",
            "dispatch_id": request["dispatch_id"],
            "actor": request["actor"],
            "capability": request["capability"],
            "work_unit": request["work_unit"],
            "mechanism": mechanism,
            "lease_id": request["lease"].get("id") if request.get("lease") else None,
            "note": "This mechanism is verified only as attended. OneCompany will not misclassify it as an automatic worker start.",
        }
        print(json.dumps(payload, indent=2))
        return 0

    payload = {
        "status": "CAPACITY_BLOCKED",
        "dispatch_id": request["dispatch_id"],
        "actor": request["actor"],
        "capability": request["capability"],
        "work_unit": request["work_unit"],
        "mechanism": mechanism,
        "reasons": ["no_reviewed_automatic_adapter_for_mechanism_kind"],
        "note": "A configured route is not considered started until a reviewed adapter returns verifiable execution evidence.",
    }
    print(json.dumps(payload, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
