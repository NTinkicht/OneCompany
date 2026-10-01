#!/usr/bin/env python3
"""Durable GitHub-backed ledger contract for Claude-exact L5 controllers.

The authoritative ledger lives on ``l5/controller-ledger`` at
``.l5/controller-ledger.json``. A network adapter MUST use the current GitHub
blob SHA as the storage CAS precondition. This module validates the document and
enforces record-level monotonicity; it performs no network I/O.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Mapping

from l5_kernel import HUMAN_CLEAR_ONLY, RepoMode, SHA40

SCHEMA_VERSION = 2
LEDGER_PATH = ".l5/controller-ledger.json"
LEDGER_BRANCH = "l5/controller-ledger"


class LedgerConflict(RuntimeError):
    """Raised when a CAS precondition or state transition is stale."""


class LedgerInvalid(ValueError):
    """Raised when durable state is malformed or unsafe."""


def _sha(value: Any) -> bool:
    """Return True for a 40-character hex SHA."""
    return isinstance(value, str) and bool(SHA40.fullmatch(value))


def _validate_observation(row: Any) -> None:
    """Validate a persisted lease observation."""
    if not isinstance(row, Mapping):
        raise LedgerInvalid("LEASE_OBSERVATION")
    if not _sha(row.get("head")) or not _sha(row.get("base")):
        raise LedgerInvalid("LEASE_OBSERVATION_REFS")
    if not isinstance(row.get("wu_body_hash", ""), str):
        raise LedgerInvalid("LEASE_OBSERVATION_WU_HASH")
    if not isinstance(row.get("pr_updated_at", ""), str):
        raise LedgerInvalid("LEASE_OBSERVATION_UPDATED_AT")


def _validate_intent(row: Any, epoch: int) -> None:
    """Validate a persisted write-ahead intent."""
    if row is None:
        return
    if not isinstance(row, Mapping):
        raise LedgerInvalid("LEASE_INTENT")
    for key in ("op_id", "idem_key", "operation"):
        if not isinstance(row.get(key), str) or not row[key]:
            raise LedgerInvalid(f"LEASE_INTENT_{key.upper()}")
    if not _sha(row.get("expected_head")) or not _sha(row.get("expected_base")):
        raise LedgerInvalid("LEASE_INTENT_REFS")
    if row.get("epoch") != epoch:
        raise LedgerInvalid("LEASE_INTENT_EPOCH")
    if row.get("state") not in {"PENDING", "DONE", "ABORTED"}:
        raise LedgerInvalid("LEASE_INTENT_STATE")


def validate_lease_record(row: Any) -> None:
    """Validate a durable active/released lease record."""
    if not isinstance(row, Mapping):
        raise LedgerInvalid("LEASE_RECORD")
    if type(row.get("version")) is not int or row["version"] < 1:
        raise LedgerInvalid("LEASE_RECORD_VERSION")
    if type(row.get("epoch")) is not int or row["epoch"] < 1:
        raise LedgerInvalid("LEASE_RECORD_EPOCH")
    if not isinstance(row.get("holder"), str) or not row["holder"]:
        raise LedgerInvalid("LEASE_RECORD_HOLDER")
    if row.get("state") not in {"ACTIVE", "RELEASED"}:
        raise LedgerInvalid("LEASE_RECORD_STATE")
    if not isinstance(row.get("acquired_at"), (int, float)):
        raise LedgerInvalid("LEASE_RECORD_ACQUIRED_AT")
    if not isinstance(row.get("expires_at"), (int, float)):
        raise LedgerInvalid("LEASE_RECORD_EXPIRES_AT")
    _validate_observation(row.get("observed"))
    _validate_intent(row.get("intent"), row["epoch"])
    if row["state"] == "RELEASED":
        intent = row.get("intent")
        if isinstance(intent, Mapping) and intent.get("state") == "PENDING":
            raise LedgerInvalid("LEASE_RELEASED_WITH_PENDING_INTENT")


def validate_budget_record(row: Any) -> None:
    """Validate a durable bounded-work budget record."""
    if not isinstance(row, Mapping):
        raise LedgerInvalid("BUDGET_RECORD")
    if type(row.get("version")) is not int or row["version"] < 1:
        raise LedgerInvalid("BUDGET_RECORD_VERSION")
    for key in ("ci_reruns", "fix_iterations", "review_rounds", "lease_acquisitions"):
        if type(row.get(key)) is not int or row[key] < 0:
            raise LedgerInvalid(f"BUDGET_{key.upper()}")


def validate_ledger(doc: Mapping[str, Any], *, expected_repo: str | None = None) -> None:
    """Validate the complete durable ledger document."""
    if not isinstance(doc, Mapping):
        raise LedgerInvalid("LEDGER_NOT_OBJECT")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise LedgerInvalid("LEDGER_SCHEMA")
    repo = doc.get("repository")
    if not isinstance(repo, str) or not repo:
        raise LedgerInvalid("LEDGER_REPOSITORY")
    if expected_repo is not None and repo != expected_repo:
        raise LedgerInvalid("LEDGER_REPOSITORY_MISMATCH")
    if type(doc.get("revision")) is not int or doc["revision"] < 0:
        raise LedgerInvalid("LEDGER_REVISION")
    try:
        mode = RepoMode(doc.get("mode"))
    except Exception as exc:
        raise LedgerInvalid("LEDGER_MODE") from exc
    if type(doc.get("mode_version")) is not int or doc["mode_version"] < 1:
        raise LedgerInvalid("LEDGER_MODE_VERSION")
    if type(doc.get("human_clear_required")) is not bool:
        raise LedgerInvalid("LEDGER_HUMAN_CLEAR")
    if mode in HUMAN_CLEAR_ONLY and doc["human_clear_required"] is not True:
        raise LedgerInvalid("LEDGER_HUMAN_CLEAR_REQUIRED")

    leases = doc.get("leases")
    budgets = doc.get("budgets")
    observations = doc.get("observations")
    if not isinstance(leases, Mapping):
        raise LedgerInvalid("LEDGER_LEASES")
    if not isinstance(budgets, Mapping):
        raise LedgerInvalid("LEDGER_BUDGETS")
    if not isinstance(observations, Mapping):
        raise LedgerInvalid("LEDGER_OBSERVATIONS")
    for row in leases.values():
        validate_lease_record(row)
    for row in budgets.values():
        validate_budget_record(row)

    enforcement = doc.get("platform_enforcement")
    if (
        not isinstance(enforcement, Mapping)
        or type(enforcement.get("branch_protected")) is not bool
        or type(enforcement.get("active_rulesets")) is not int
        or enforcement["active_rulesets"] < 0
    ):
        raise LedgerInvalid("LEDGER_PLATFORM_ENFORCEMENT")


def canonical_json(doc: Mapping[str, Any]) -> str:
    """Serialize a validated ledger deterministically."""
    validate_ledger(doc)
    return json.dumps(doc, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def blob_cas_ok(observed_blob_sha: str, expected_blob_sha: str) -> bool:
    """Check GitHub blob-SHA CAS evidence."""
    return (
        isinstance(observed_blob_sha, str)
        and bool(observed_blob_sha)
        and observed_blob_sha == expected_blob_sha
    )


def _begin(doc: Mapping[str, Any], expected_revision: int) -> dict[str, Any]:
    """Clone a ledger after checking document revision."""
    validate_ledger(doc)
    if doc["revision"] != expected_revision:
        raise LedgerConflict("LEDGER_REVISION_STALE")
    out = copy.deepcopy(dict(doc))
    out["revision"] += 1
    return out


def cas_mode(
    doc: Mapping[str, Any],
    *,
    expected_revision: int,
    expected_mode_version: int,
    new_mode: RepoMode,
    human_clear: bool = False,
) -> dict[str, Any]:
    """CAS repository mode while enforcing human-only exits."""
    out = _begin(doc, expected_revision)
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


def _validate_lease_transition(cur: Mapping[str, Any] | None, row: Mapping[str, Any]) -> None:
    """Enforce monotonic lease epoch/version and intent preservation."""
    validate_lease_record(row)
    if cur is None:
        if row["version"] != 1:
            raise LedgerInvalid("LEASE_INITIAL_VERSION")
        return

    validate_lease_record(cur)
    if row["version"] <= cur["version"]:
        raise LedgerInvalid("LEASE_VERSION_NOT_MONOTONIC")
    same_owner_epoch = row["holder"] == cur["holder"] and row["epoch"] == cur["epoch"]
    new_owner_epoch = row["holder"] != cur["holder"] and row["epoch"] > cur["epoch"]
    same_holder_new_epoch = row["holder"] == cur["holder"] and row["epoch"] > cur["epoch"]
    if not (same_owner_epoch or new_owner_epoch or same_holder_new_epoch):
        raise LedgerInvalid("LEASE_EPOCH_NOT_MONOTONIC")

    cur_intent = cur.get("intent")
    next_intent = row.get("intent")
    if isinstance(cur_intent, Mapping) and cur_intent.get("state") == "PENDING":
        if not isinstance(next_intent, Mapping):
            raise LedgerConflict("PENDING_INTENT_LOST")
        if next_intent.get("op_id") != cur_intent.get("op_id"):
            raise LedgerConflict("PENDING_INTENT_REPLACED")
        if next_intent.get("state") not in {"PENDING", "DONE", "ABORTED"}:
            raise LedgerInvalid("PENDING_INTENT_TRANSITION")
        if row["epoch"] != cur["epoch"] or row["holder"] != cur["holder"]:
            raise LedgerConflict("PENDING_INTENT_REASSIGNED")

    if cur.get("state") == "ACTIVE" and row.get("state") == "RELEASED":
        intent = row.get("intent")
        if isinstance(intent, Mapping) and intent.get("state") == "PENDING":
            raise LedgerConflict("PENDING_INTENT_RELEASE")


def cas_lease(
    doc: Mapping[str, Any],
    key: str,
    *,
    expected_revision: int,
    expected_lease_version: int | None,
    new_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """CAS a lease record; deletion is forbidden, release uses tombstones."""
    if not isinstance(key, str) or not key:
        raise LedgerInvalid("LEASE_KEY")
    if new_record is None:
        raise LedgerInvalid("LEASE_DELETE_FORBIDDEN")
    out = _begin(doc, expected_revision)
    cur = out["leases"].get(key)
    actual = None if cur is None else cur.get("version")
    if actual != expected_lease_version:
        raise LedgerConflict("LEASE_VERSION_STALE")
    row = copy.deepcopy(dict(new_record))
    _validate_lease_transition(cur, row)
    out["leases"][key] = row
    validate_ledger(out)
    return out


def cas_budget(
    doc: Mapping[str, Any],
    key: str,
    *,
    expected_revision: int,
    expected_budget_version: int | None,
    new_record: Mapping[str, Any],
) -> dict[str, Any]:
    """CAS a bounded-work budget record."""
    out = _begin(doc, expected_revision)
    cur = out["budgets"].get(key)
    actual = None if cur is None else cur.get("version")
    if actual != expected_budget_version:
        raise LedgerConflict("BUDGET_VERSION_STALE")
    row = copy.deepcopy(dict(new_record))
    validate_budget_record(row)
    if expected_budget_version is None:
        if row["version"] != 1:
            raise LedgerInvalid("BUDGET_INITIAL_VERSION")
    elif row["version"] <= expected_budget_version:
        raise LedgerInvalid("BUDGET_VERSION_NOT_MONOTONIC")
    out["budgets"][key] = row
    validate_ledger(out)
    return out
