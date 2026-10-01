#!/usr/bin/env python3
"""Production durable CASStore over the GitHub controller-ledger branch.

This module is credential-isolated: a backend owns GitHub authentication and
performs exactly two operations, read the authoritative ledger and compare-and-
swap its blob. The store converts durable JSON records to kernel values and
applies the schema/record transition checks in :mod:`l5_ledger` before every
write.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from l5_kernel import Intent, Lease, Observation, RepoMode
from l5_ledger import (
    LedgerConflict,
    canonical_json,
    cas_lease,
    cas_mode,
    validate_ledger,
)


class LedgerBackend(Protocol):
    """Minimal credential-bearing backend for the dedicated ledger branch."""

    def read_ledger(self) -> tuple[Mapping[str, Any], str]: ...
    def compare_and_swap(self, expected_blob_sha: str, content: str) -> bool: ...


class DurableLedgerCASStore:
    """Cross-run authoritative CASStore backed by GitHub blob-SHA CAS."""

    def __init__(self, repo_id: str, backend: LedgerBackend):
        """Bind one repository ledger to one credential-isolated backend."""
        if not isinstance(repo_id, str) or not repo_id:
            raise ValueError("L5_LEDGER_REPO_INVALID")
        self.repo_id = repo_id
        self.backend = backend

    def _read(self) -> tuple[dict[str, Any], str]:
        """Read and validate the current authoritative ledger/blob identity."""
        doc, blob_sha = self.backend.read_ledger()
        validate_ledger(doc, expected_repo=self.repo_id)
        if not isinstance(blob_sha, str) or not blob_sha:
            raise ValueError("L5_LEDGER_BLOB_SHA_INVALID")
        return dict(doc), blob_sha

    @staticmethod
    def _observation_from_record(row: Mapping[str, Any]) -> Observation:
        """Deserialize a persisted observation."""
        return Observation(
            head=row["head"],
            base=row["base"],
            wu_body_hash=row.get("wu_body_hash", ""),
            pr_updated_at=row.get("pr_updated_at", ""),
        )

    @staticmethod
    def _intent_from_record(row: Mapping[str, Any] | None) -> Intent | None:
        """Deserialize a persisted intent."""
        if row is None:
            return None
        return Intent(
            op_id=row["op_id"],
            idem_key=row["idem_key"],
            operation=row["operation"],
            expected_head=row["expected_head"],
            expected_base=row["expected_base"],
            epoch=row["epoch"],
            state=row["state"],
        )

    @classmethod
    def _lease_from_record(cls, key: str, row: Mapping[str, Any]) -> Lease:
        """Deserialize one durable lease/tombstone."""
        return Lease(
            key=key,
            holder=row["holder"],
            epoch=row["epoch"],
            observed=cls._observation_from_record(row["observed"]),
            acquired_at=float(row["acquired_at"]),
            expires_at=float(row["expires_at"]),
            version=row["version"],
            intent=cls._intent_from_record(row.get("intent")),
            state=row["state"],
        )

    @staticmethod
    def _intent_record(intent: Intent | None) -> dict[str, Any] | None:
        """Serialize an intent for the durable ledger."""
        if intent is None:
            return None
        return {
            "op_id": intent.op_id,
            "idem_key": intent.idem_key,
            "operation": intent.operation,
            "expected_head": intent.expected_head,
            "expected_base": intent.expected_base,
            "epoch": intent.epoch,
            "state": intent.state,
        }

    @classmethod
    def _lease_record(
        cls,
        lease: Lease,
        current: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Serialize a lease with an explicit ACTIVE/RELEASED state."""
        if lease.state not in {"ACTIVE", "RELEASED"}:
            raise ValueError("L5_LEASE_STATE_INVALID")
        return {
            "version": lease.version,
            "epoch": lease.epoch,
            "holder": lease.holder,
            "state": lease.state,
            "acquired_at": lease.acquired_at,
            "expires_at": lease.expires_at,
            "observed": {
                "head": lease.observed.head,
                "base": lease.observed.base,
                "wu_body_hash": lease.observed.wu_body_hash,
                "pr_updated_at": lease.observed.pr_updated_at,
            },
            "intent": cls._intent_record(lease.intent),
        }

    def read(self, key: str) -> Lease | None:
        """Read one durable lease/tombstone."""
        doc, _ = self._read()
        row = doc["leases"].get(key)
        return None if row is None else self._lease_from_record(key, row)

    def cas(
        self,
        key: str,
        expected_version: int | None,
        value: Lease,
    ) -> bool:
        """CAS one lease through record version plus GitHub blob identity."""
        doc, blob_sha = self._read()
        current = doc["leases"].get(key)
        actual = None if current is None else current.get("version")
        if actual != expected_version:
            return False
        try:
            updated = cas_lease(
                doc,
                key,
                expected_revision=doc["revision"],
                expected_lease_version=expected_version,
                new_record=self._lease_record(value, current),
            )
        except LedgerConflict:
            return False
        return self.backend.compare_and_swap(blob_sha, canonical_json(updated))

    def read_repo_mode(self, repo_id: str) -> tuple[RepoMode, int | None]:
        """Read the persisted repository mode/version."""
        if repo_id != self.repo_id:
            raise ValueError("L5_LEDGER_REPO_MISMATCH")
        doc, _ = self._read()
        return RepoMode(doc["mode"]), doc["mode_version"]

    def cas_repo_mode(
        self,
        repo_id: str,
        expected_version: int | None,
        mode: RepoMode,
        *,
        human_clear: bool = False,
        post_merge_verified: bool = False,
    ) -> bool:
        """CAS repository mode through mode version plus GitHub blob identity."""
        if repo_id != self.repo_id or expected_version is None:
            return False
        doc, blob_sha = self._read()
        if doc["mode_version"] != expected_version:
            return False
        try:
            updated = cas_mode(
                doc,
                expected_revision=doc["revision"],
                expected_mode_version=expected_version,
                new_mode=mode,
                human_clear=human_clear,
                post_merge_verified=post_merge_verified,
            )
        except LedgerConflict:
            return False
        return self.backend.compare_and_swap(blob_sha, canonical_json(updated))

    def list_leases(self) -> list[Lease]:
        """Return all durable lease records, including released tombstones."""
        doc, _ = self._read()
        return [
            self._lease_from_record(key, row)
            for key, row in sorted(doc["leases"].items())
        ]
