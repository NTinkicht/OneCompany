"""Fail-closed attribution of a PR approval from exact-head reviews (#369).

OC-P0-01 / OC-P0-05: ``PullRequestObservation`` carries one approval triple
(``approved_head_sha``, ``approved_base_sha``, ``approved_by``). This module
derives that triple from the raw reviews a trusted caller fetched
(``GET /pulls/{n}/reviews``) instead of trusting a pre-assembled claim.

An approval counts only when the latest decisive review (highest id,
``APPROVED`` or ``CHANGES_REQUESTED``) by an exactly-declared trusted
reviewer on the exact head is an approval whose body carries exactly one
well-formed reviewer marker for that head, in ``approve`` mode, naming the
base it was produced on. ``DISMISSED`` and ``COMMENTED`` reviews never count.
Base freshness against live main is judged by ``pr_inconsistencies``.

Read-only and pure: nothing here fetches, approves, dismisses or merges.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SHA = re.compile(r"[0-9a-f]{40}")
# Same shape as REVIEW_MARK in .github/ntk-reviewer/review.py.
_MARKER_PREFIX = "<!-- ntk-review v1 "
_MARKER = re.compile(r"<!-- ntk-review v1 head=([0-9a-f]{40}) mode=(comment|approve) "
                     r"(?:base=([0-9a-f]{40}) )?")
_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED"})
_DECISIVE = frozenset({"APPROVED", "CHANGES_REQUESTED"})


@dataclass(frozen=True)
class ReviewObservation:
    """One submitted review as fetched by the trusted caller."""
    id: int
    reviewer: str
    state: str
    commit_id: str
    body: str


@dataclass(frozen=True)
class ApprovalAttribution:
    approved_head_sha: str | None
    approved_base_sha: str | None
    approved_by: str | None
    findings: tuple[tuple[str, str], ...]


_NONE = (None, None, None)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _valid_review(review: object) -> bool:
    if not isinstance(review, ReviewObservation):
        return False
    if type(review.id) is not int or review.id <= 0:  # a bool is never an id
        return False
    return (_text(review.reviewer) and review.state in _STATES
            and _valid_sha(review.commit_id) and isinstance(review.body, str))


def _marker_finding(review: ReviewObservation, head_sha: str) -> tuple[str | None, str | None]:
    """Return ``(base, None)`` for a valid approval marker, else ``(None, FINDING)``."""
    if review.body.count(_MARKER_PREFIX) != 1:
        # Zero, or a second (e.g. echoed in a model summary): ambiguous.
        return None, "INVALID_APPROVAL_MARKER"
    match = _MARKER.search(review.body)
    if match is None:
        return None, "INVALID_APPROVAL_MARKER"
    marked_head, mode, marked_base = match.groups()
    if marked_head != review.commit_id or marked_head != head_sha:
        return None, "MARKER_HEAD_MISMATCH"
    if mode != "approve":
        return None, "MARKER_NOT_APPROVE_MODE"
    if marked_base is None:
        return None, "APPROVAL_WITHOUT_BASE"
    return marked_base, None


def attribute_approval(
    reviews: tuple[ReviewObservation, ...],
    head_sha: str,
    trusted_reviewers: tuple[str, ...],
) -> ApprovalAttribution:
    """Return the exact-head approval triple with stable sorted findings.

    Findings are ``(review id or "", CODE)``. Any ``INVALID_*`` finding
    withholds attribution entirely. Trust is an exact login match, as in
    ``live_work_reconciliation._trusted_approver``.
    """
    findings: set[tuple[str, str]] = set()
    invalid = False
    if not _valid_sha(head_sha):
        findings.add(("", "INVALID_SHA"))
        invalid = True

    valid_trusted = (isinstance(trusted_reviewers, tuple) and bool(trusted_reviewers)
                     and all(_text(r) for r in trusted_reviewers))
    if not valid_trusted:
        findings.add(("", "INVALID_TRUSTED_REVIEWERS"))
        invalid = True
    trusted = frozenset(trusted_reviewers) if valid_trusted else frozenset()

    review_list = reviews if isinstance(reviews, tuple) else ()
    if not isinstance(reviews, tuple):
        findings.add(("", "INVALID_REVIEW"))
        invalid = True
    valid: list[ReviewObservation] = []
    seen_ids: set[int] = set()
    for review in review_list:
        if not _valid_review(review) or review.id in seen_ids:
            ref = (str(review.id) if isinstance(review, ReviewObservation)
                   and type(review.id) is int and review.id > 0 else "")
            findings.add((ref, "INVALID_REVIEW"))
            invalid = True
            continue
        seen_ids.add(review.id)
        valid.append(review)

    if invalid:
        return ApprovalAttribution(*_NONE, tuple(sorted(findings)))

    for review in valid:
        if review.state == "APPROVED" and review.reviewer not in trusted:
            findings.add((str(review.id), "UNTRUSTED_REVIEWER_APPROVAL"))

    decisive = [r for r in valid if r.reviewer in trusted and r.state in _DECISIVE]
    on_head = [r for r in decisive if r.commit_id == head_sha]
    if not on_head:
        if any(r.state == "APPROVED" for r in decisive):
            findings.add(("", "STALE_HEAD_APPROVAL"))
        return ApprovalAttribution(*_NONE, tuple(sorted(findings)))

    latest = max(on_head, key=lambda r: r.id)
    if latest.state == "CHANGES_REQUESTED":
        findings.add((str(latest.id), "CHANGES_REQUESTED"))
        return ApprovalAttribution(*_NONE, tuple(sorted(findings)))

    base, problem = _marker_finding(latest, head_sha)
    if problem is not None:
        findings.add((str(latest.id), problem))
        return ApprovalAttribution(*_NONE, tuple(sorted(findings)))
    return ApprovalAttribution(head_sha, base, latest.reviewer, tuple(sorted(findings)))
