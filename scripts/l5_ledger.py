#!/usr/bin/env python3
"""Durable GitHub-ledger contract for Claude L5 controllers.

The ledger document is stored on ``l5/controller-ledger``. The network adapter
must update the file through GitHub's contents API using the exact observed blob
SHA. This module validates persisted state and enforces monotonic lease/epoch
history; it contains no credentials.
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict
from typing import Any, Callable, Mapping, Protocol

from l5_kernel import HUMAN_CLEAR_ONLY, Intent, Lease, Observation, RepoMode

SCHEMA_VERSION = 2
LEDGER_PATH = ".l5/controller-ledger.json"
LEDGER_BRANCH = "l5/controller-ledger"


class LedgerConflict(RuntimeError):
    """Raised on stale compare-and-swap state."""


class LedgerInvalid(ValueError):
    """Raised when ledger data violates the durable schema."""


class LedgerBackend(Protocol):
    """Transport boundary for GitHub contents read/update operations."""

    def read(self) -> tuple[Mapping[str, Any], str]: ...
    def write(self, document: Mapping[str, Any], expected_blob_sha: str) -> str: ...


def _validate_observation(value: Any) -> None:
    """Validate a persisted resource observation."""
    if not isinstance(value, Mapping):
        raise LedgerInvalid("LEASE_OBSERVATION")
    for key in ("head", "base", "wu_body_hash", "pr_updated_at"):
        if not isinstance(value.get(key), str):
            raise LedgerInvalid("LEASE_OBSERVATION")


def _validate_intent(value: Any, epoch: int) -> None:
    """Validate a persisted intent."""
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise LedgerInvalid("LEASE_INTENT")
    for key in ("op_id", "idem_key", "operation", "expected_head", "expected_base", "state"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise LedgerInvalid("LEASE_INTENT")
    if value.get("state") not in {"PENDING", "DONE", "ABORTED"}:
        raise LedgerInvalid("LEASE_INTENT_STATE")
    if value.get("epoch") != epoch:
        raise LedgerInvalid("LEASE_INTENT_EPOCH")


def _validate_lease_record(value: Any) -> None:
    """Validate a persisted lease or tombstone."""
    if not isinstance(value, Mapping):
        raise LedgerInvalid("LEASE_RECORD")
    if type(value.get("version")) is not int or value["version"] < 1:
        raise LedgerInvalid("LEASE_RECORD_VERSION")
    if type(value.get("epoch")) is not int or value["epoch"] < 1:
        raise LedgerInvalid("LEASE_RECORD_EPOCH")
    if not isinstance(value.get("holder"), str) or not value["holder"]:
        raise LedgerInvalid("LEASE_RECORD_HOLDER")
    if type(value.get("active")) is not bool:
        raise LedgerInvalid("LEASE_RECORD_ACTIVE")
    if not isinstance(value.get("acquired_at"), (int, float)):
        raise LedgerInvalid("LEASE_ACQUIRED_AT")
    if not isinstance(value.get("expires_at"), (int, float)):
        raise LedgerInvalid("LEASE_EXPIRES_AT")
    _validate_observation(value.get("observed"))
    _validate_intent(value.get("intent"), value["epoch"])
    if not value["active"]:
        intent = value.get("intent")
        if intent is not None and intent.get("state") == "PENDING":
            raise LedgerInvalid("INACTIVE_PENDING_INTENT")


def validate_ledger(document: Mapping[str, Any], *, expected_repo: str | None = None) -> None:
    """Validate the complete durable ledger document."""
    if not isinstance(document, Mapping):
        raise LedgerInvalid("LEDGER_NOT_OBJECT")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise LedgerInvalid("LEDGER_SCHEMA")
    repo = document.get("repository")
    if not isinstance(repo, str) or not repo:
        raise LedgerInvalid("LEDGER_REPOSITORY")
    if expected_repo is not None and repo != expected_repo:
        raise LedgerInvalid("LEDGER_REPOSITORY_MISMATCH")
    if type(document.get("revision")) is not int or document["revision"] < 0:
        raise LedgerInvalid("LEDGER_REVISION")
    try:
        mode = RepoMode(document.get("mode"))
    except Exception as exc:
        raise LedgerInvalid("LEDGER_MODE") from exc
    if type(document.get("mode_version")) is not int or document["mode_version"] < 1:
        raise LedgerInvalid("LEDGER_MODE_VERSION")
    if type(document.get("human_clear_required")) is not bool:
        raise LedgerInvalid("LEDGER_HUMAN_CLEAR")
    if mode in HUMAN_CLEAR_ONLY and document["human_clear_required"] is not True:
        raise LedgerInvalid("LEDGER_HUMAN_CLEAR_REQUIRED")
    for key in ("leases", "budgets", "observations"):
        if not isinstance(document.get(key), Mapping):
            raise LedgerInvalid(f"LEDGER_{key.upper()}")
    for record in document["leases"].values():
        _validate_lease_record(record)
    enforcement = document.get("platform_enforcement")
    if (
        not isinstance(enforcement, Mapping)
        or type(enforcement.get("branch_protected")) is not bool
        or type(enforcement.get("active_rulesets")) is not int
        or enforcement["active_rulesets"] < 0
    ):
        raise LedgerInvalid("LEDGER_PLATFORM_ENFORCEMENT")


def canonical_json(document: Mapping[str, Any]) -> str:
    """Serialize a validated ledger deterministically."""
    validate_ledger(document)
    return json.dumps(document, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def blob_cas_ok(observed_blob_sha: str, expected_blob_sha: str) -> bool:
    """Validate the outer GitHub file CAS precondition."""
    return isinstance(observed_blob_sha, str) and bool(observed_blob_sha) and observed_blob_sha == expected_blob_sha


def _begin(document: Mapping[str, Any], expected_revision: int) -> dict[str, Any]:
    """Clone a ledger and advance its document revision."""
    validate_ledger(document)
    if document["revision"] != expected_revision:
        raise LedgerConflict("LEDGER_REVISION_STALE")
    out = copy.deepcopy(dict(document))
    out["revision"] += 1
    return out


def cas_mode(
    document: Mapping[str, Any],
    *,
    expected_revision: int,
    expected_mode_version: int,
    new_mode: RepoMode,
    human_clear: bool = False,
) -> dict[str, Any]:
    """CAS repository mode, preserving human-only exits."""
    out = _begin(document, expected_revision)
    if out["mode_version"] != expected_mode_version:
        raise LedgerConflict("MODE_VERSION_STALE")
    old = RepoMode(out["mode"])
    if old in HUMAN_CLEAR_ONLY and old != new_mode and not human_clear:
        raise LedgerConflict("HUMAN_CLEAR_REQUIRED")
    out["mode"] = new_mode.value
    out["mode_version"] += 1
    out["human_clear_required"] = new_mode in HUMAN_CLEAR_ONLY
    validate_ledger(out)
    return out


def lease_to_record(lease: Lease) -> dict[str, Any]:
    """Convert an in-memory lease to its durable representation."""
    return asdict(lease)


def record_to_lease(key: str, record: Mapping[str, Any]) -> Lease:
    """Convert a validated durable record to a lease object."""
    _validate_lease_record(record)
    observation = Observation(**dict(record["observed"]))
    intent_data = record.get("intent")
    intent = Intent(**dict(intent_data)) if intent_data is not None else None
    return Lease(
        key=key,
        holder=record["holder"],
        epoch=record["epoch"],
        observed=observation,
        acquired_at=record["acquired_at"],
        expires_at=record["expires_at"],
        version=record["version"],
        intent=intent,
        active=record["active"],
    )


def cas_lease(
    document: Mapping[str, Any],
    key: str,
    *,
    expected_revision: int,
    expected_lease_version: int | None,
    new_record: Mapping[str, Any],
) -> dict[str, Any]:
    """CAS a lease/tombstone while preserving version and epoch floors."""
    if not isinstance(key, str) or not key:
        raise LedgerInvalid("LEASE_KEY")
    _validate_lease_record(new_record)
    out = _begin(document, expected_revision)
    current = out["leases"].get(key)
    actual = None if current is None else current.get("version")
    if actual != expected_lease_version:
        raise LedgerConflict("LEASE_VERSION_STALE")
    row = copy.deepcopy(dict(new_record))
    if current is None:
        if row["version"] != 1 or row["epoch"] != 1:
            raise LedgerInvalid("LEASE_INITIAL_VERSION_EPOCH")
    else:
        _validate_lease_record(current)
        if row["version"] <= current["version"]:
            raise LedgerInvalid("LEASE_VERSION_NOT_MONOTONIC")
        if row["epoch"] < current["epoch"]:
            raise LedgerInvalid("LEASE_EPOCH_REGRESSION")
        if row["epoch"] == current["epoch"] and row["holder"] != current["holder"]:
            raise LedgerInvalid("LEASE_HOLDER_CHANGED_WITHOUT_NEW_EPOCH")
        old_intent = current.get("intent")
        if old_intent is not None and old_intent.get("state") == "PENDING":
            new_intent = row.get("intent")
            if new_intent is None or new_intent.get("op_id") != old_intent.get("op_id"):
                raise LedgerInvalid("PENDING_INTENT_REPLACED")
        if not current["active"] and row["active"] and row["epoch"] <= current["epoch"]:
            raise LedgerInvalid("LEASE_REACTIVATION_EPOCH")
    out["leases"][key] = row
    validate_ledger(out)
    return out


def cas_budget(
    document: Mapping[str, Any],
    key: str,
    *,
    expected_revision: int,
    expected_budget_version: int | None,
    new_record: Mapping[str, Any],
) -> dict[str, Any]:
    """CAS one bounded-budget record."""
    out = _begin(document, expected_revision)
    current = out["budgets"].get(key)
    actual = None if current is None else current.get("version")
    if actual != expected_budget_version:
        raise LedgerConflict("BUDGET_VERSION_STALE")
    row = copy.deepcopy(dict(new_record))
    if type(row.get("version")) is not int or row["version"] < 1:
        raise LedgerInvalid("BUDGET_RECORD_VERSION")
    if expected_budget_version is not None and row["version"] <= expected_budget_version:
        raise LedgerInvalid("BUDGET_VERSION_NOT_MONOTONIC")
    out["budgets"][key] = row
    validate_ledger(out)
    return out


class LedgerCASStore:
    """CASStore backed by an outer GitHub-file CAS backend."""

    def __init__(self, backend: LedgerBackend, repository: str):
        self.backend = backend
        self.repository = repository

    def _read_document(self) -> tuple[dict[str, Any], str]:
        """Read and validate the authoritative document and blob SHA."""
        document, blob_sha = self.backend.read()
        validate_ledger(document, expected_repo=self.repository)
        if not isinstance(blob_sha, str) or not blob_sha:
            raise LedgerInvalid("LEDGER_BLOB_SHA")
        return copy.deepcopy(dict(document)), blob_sha

    def read(self, key: str) -> Lease | None:
        """Read a lease/tombstone from the durable ledger."""
        document, _ = self._read_document()
        record = document["leases"].get(key)
        return None if record is None else record_to_lease(key, record)

    def list_leases(self) -> list[Lease]:
        """Read all durable lease/tombstone records."""
        document, _ = self._read_document()
        return [record_to_lease(key, row) for key, row in document["leases"].items()]

    def cas(self, key: str, expected_version: int | None, value: Lease) -> bool:
        """Atomically update a lease using record CAS plus blob-SHA CAS."""
        document, blob_sha = self._read_document()
        try:
            updated = cas_lease(
                document,
                key,
                expected_revision=document["revision"],
                expected_lease_version=expected_version,
                new_record=lease_to_record(value),
            )
            self.backend.write(updated, blob_sha)
        except LedgerConflict:
            return False
        return True

    def read_repo_mode(self, repo_id: str) -> tuple[RepoMode, int | None]:
        """Read durable repository mode; missing state never defaults NORMAL."""
        if repo_id != self.repository:
            raise LedgerInvalid("LEDGER_REPOSITORY_MISMATCH")
        document, _ = self._read_document()
        return RepoMode(document["mode"]), document["mode_version"]

    def cas_repo_mode(self, repo_id: str, expected_version: int | None, mode: RepoMode) -> bool:
        """CAS durable mode without allowing implicit human-clear exits."""
        if repo_id != self.repository or expected_version is None:
            return False
        document, blob_sha = self._read_document()
        try:
            updated = cas_mode(
                document,
                expected_revision=document["revision"],
                expected_mode_version=expected_version,
                new_mode=mode,
                human_clear=False,
            )
            self.backend.write(updated, blob_sha)
        except LedgerConflict:
            return False
        return True


class CallbackGitHubLedgerBackend:
    """GitHub contents adapter using injected read/update callbacks.

    ``reader`` returns ``(document, blob_sha)`` for the canonical ledger file.
    ``writer`` performs a GitHub contents update with ``expected_blob_sha`` as
    the file-SHA precondition and returns the resulting blob SHA.
    """

    def __init__(
        self,
        reader: Callable[[], tuple[Mapping[str, Any], str]],
        writer: Callable[[str, str], str],
    ):
        self._reader = reader
        self._writer = writer

    def read(self) -> tuple[Mapping[str, Any], str]:
        """Read the canonical GitHub ledger file."""
        return self._reader()

    def write(self, document: Mapping[str, Any], expected_blob_sha: str) -> str:
        """Write the ledger through exact GitHub file-SHA CAS."""
        validate_ledger(document)
        return self._writer(canonical_json(document), expected_blob_sha)
