#!/usr/bin/env python3
"""Deterministic observation helpers for reconciling one canonical PR stream per WU.

This module deliberately does not authorize branch creation. A caller must first
obtain its separate durable atomic WU claim/lease; inventory reconciliation is
only evidence about already-observed GitHub streams.
"""
from __future__ import annotations

from dataclasses import dataclass


class IncompleteInventoryError(RuntimeError):
    pass


class ConflictingStreamObservationError(RuntimeError):
    pass


class DuplicateCanonicalStreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class Stream:
    wu_id: str
    repository: str
    branch: str
    pr_number: int
    head_sha: str
    repository_id: int | None = None


def _repository_identity(repository: str, repository_id: int | None = None) -> tuple[str, str | int]:
    """Return a stable GitHub repository identity when available.

    GitHub repository IDs survive rename/transfer. Name matching remains a
    compatibility fallback for callers that have not yet supplied the stable ID.
    """
    if repository_id is not None:
        return ("id", repository_id)
    return ("name", repository.casefold())


def _stream_payload(stream: Stream) -> tuple[str, str, str]:
    """Return the immutable fields that one repository/PR observation must agree on."""
    return (stream.wu_id, stream.branch, stream.head_sha)


def canonical_stream(
    streams: list[Stream],
    *,
    repository: str,
    wu_id: str,
    snapshot_complete: bool,
    repository_id: int | None = None,
) -> Stream | None:
    """Reconcile a verified-complete observation of canonical PR streams.

    Replayed identical observations of the same immutable repository/PR identity
    collapse to one stream. Contradictory observations for the same PR or reuse
    of one canonical branch across Work Units fail closed before Work Unit
    filtering, as do multiple distinct PR streams for the requested WU.
    Stable GitHub repository IDs are preferred so rename/transfer aliases cannot
    hide an existing stream; case-insensitive names are the compatibility fallback.
    An empty result is meaningful only when the caller explicitly supplies a
    verified-complete snapshot.

    This function is not a start gate and never grants a branch/PR lease.
    """
    if snapshot_complete is not True:
        raise IncompleteInventoryError("CANONICAL_STREAM_INVENTORY_INCOMPLETE")

    by_identity: dict[tuple[tuple[str, str | int], int], list[Stream]] = {}
    for stream in streams:
        identity = (_repository_identity(stream.repository, stream.repository_id), stream.pr_number)
        by_identity.setdefault(identity, []).append(stream)

    canonical_observations: list[Stream] = []
    for identity in sorted(by_identity, key=repr):
        observations = sorted(
            by_identity[identity],
            key=lambda item: (
                item.wu_id,
                item.branch,
                item.head_sha,
                item.repository.casefold(),
                item.repository,
            ),
        )
        payloads = sorted({_stream_payload(item) for item in observations})
        if len(payloads) > 1:
            raise ConflictingStreamObservationError(
                "CANONICAL_STREAM_OBSERVATION_CONFLICT:"
                f"{identity[0]}:{identity[1]}:{payloads}"
            )
        canonical_observations.append(observations[0])

    by_branch: dict[tuple[tuple[str, str | int], str], list[Stream]] = {}
    for stream in canonical_observations:
        identity = (_repository_identity(stream.repository, stream.repository_id), stream.branch)
        by_branch.setdefault(identity, []).append(stream)
    for identity in sorted(by_branch, key=repr):
        observations = by_branch[identity]
        wu_ids = sorted({item.wu_id for item in observations})
        if len(wu_ids) > 1:
            raise ConflictingStreamObservationError(
                "CANONICAL_BRANCH_WU_CONFLICT:"
                f"{identity[0]}:{identity[1]}:{wu_ids}"
            )

    requested_repository = _repository_identity(repository, repository_id)
    matches = [
        stream
        for stream in canonical_observations
        if _repository_identity(stream.repository, stream.repository_id) == requested_repository
        and stream.wu_id == wu_id
    ]
    if len(matches) > 1:
        identities = sorted((s.pr_number, s.branch, s.head_sha) for s in matches)
        raise DuplicateCanonicalStreamError(f"DUPLICATE_CANONICAL_STREAMS:{identities}")
    return matches[0] if matches else None
