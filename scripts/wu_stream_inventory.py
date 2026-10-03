#!/usr/bin/env python3
"""Deterministic helpers for reconciling one canonical PR stream per Work Unit."""
from __future__ import annotations

from dataclasses import dataclass


class DuplicateCanonicalStreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class Stream:
    wu_id: str
    repository: str
    branch: str
    pr_number: int
    head_sha: str


def canonical_stream(streams: list[Stream], *, repository: str, wu_id: str) -> Stream | None:
    """Return the unique canonical stream, or fail closed on duplicates."""
    matches = [s for s in streams if s.repository == repository and s.wu_id == wu_id]
    if len(matches) > 1:
        identities = sorted((s.pr_number, s.branch, s.head_sha) for s in matches)
        raise DuplicateCanonicalStreamError(f"DUPLICATE_CANONICAL_STREAMS:{identities}")
    return matches[0] if matches else None


def may_start_new_stream(streams: list[Stream], *, repository: str, wu_id: str) -> bool:
    """A new implementation stream is allowed only when no canonical stream exists."""
    return canonical_stream(streams, repository=repository, wu_id=wu_id) is None
