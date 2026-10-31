"""Fail-closed review-conversation evidence for one PR head (#377).

OC-P0-01 / OC-P0-05 / OC-P0-06: a PR is merge-ready only when every review
conversation is resolved. This module judges the raw review threads a
trusted caller fetched for the PR (every page, as GitHub returns them)
instead of trusting a pre-assembled "conversations resolved" claim.

An outdated thread (its lines changed since) is still a conversation:
GitHub's "require conversation resolution" counts it until it is resolved,
so it is never treated as settled here either. A list the caller did not
page to the end is never proof that no unresolved thread exists.

Read-only and pure: nothing here fetches, resolves, approves or merges.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewThreadObservation:
    """One review thread as fetched by the trusted caller."""
    id: str
    is_resolved: bool
    is_outdated: bool


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def review_thread_findings(
    threads: tuple[ReviewThreadObservation, ...], complete: bool,
) -> tuple[tuple[str, str], ...]:
    """Return stable sorted ``(thread id or "", FINDING)`` pairs.

    Empty means every observed thread is resolved and the list is complete.
    Malformed input is reported, never coerced: a non-boolean flag (``1``,
    ``"false"``) is ``INVALID_REVIEW_THREAD`` rather than read as truthy.
    """
    problems: set[tuple[str, str]] = set()
    if complete is not True:
        problems.add(("", "REVIEW_THREADS_INCOMPLETE"))
    if not isinstance(threads, tuple):
        problems.add(("", "INVALID_REVIEW_THREAD"))
        return tuple(sorted(problems))
    seen: set[str] = set()
    for thread in threads:
        if not isinstance(thread, ReviewThreadObservation) or not _valid_id(thread.id):
            problems.add(("", "INVALID_REVIEW_THREAD"))
            continue
        ref = thread.id
        if ref in seen:
            problems.add((ref, "DUPLICATE_REVIEW_THREAD"))
        seen.add(ref)
        if type(thread.is_resolved) is not bool or type(thread.is_outdated) is not bool:
            problems.add((ref, "INVALID_REVIEW_THREAD"))
            continue
        if not thread.is_resolved:
            problems.add((ref, "UNRESOLVED_REVIEW_THREAD"))
    return tuple(sorted(problems))
