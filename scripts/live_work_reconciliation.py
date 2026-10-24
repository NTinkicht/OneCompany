"""Read-only consistency checks for a synthetic live work snapshot.

Caller must acquire the actual GitHub and ledger data from trusted sources.
This module never claims a lease, merges, or modifies the queue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class WorkSnapshot:
    main_sha: str
    observed_main_sha: str
    issue_ids: tuple[int, ...]
    next_ids: tuple[int, ...]
    pr_issue_bindings: tuple[tuple[int, int], ...]
    active_lease_issue_ids: tuple[int, ...]
    retired_pilot_issue_ids: tuple[int, ...] = ()


def _valid_work_id(value: object) -> bool:
    """Reject Python bool aliases and non-positive/non-integer work IDs."""
    return type(value) is int and value > 0


def inconsistencies(snapshot: WorkSnapshot) -> tuple[str, ...]:
    """Return stable fail-closed findings, with no inferred permissions."""
    problems: set[str] = set()
    issue_ids = (*snapshot.issue_ids, *snapshot.next_ids,
                 *(issue for _, issue in snapshot.pr_issue_bindings),
                 *snapshot.active_lease_issue_ids, *snapshot.retired_pilot_issue_ids)
    if any(not _valid_work_id(issue) for issue in issue_ids):
        problems.add("INVALID_ISSUE_ID")
    if any(not _valid_work_id(pr) for pr, _ in snapshot.pr_issue_bindings):
        problems.add("INVALID_PR_ID")
    # Same rule as the PR checks: only two equal well-formed lowercase
    # 40-hex SHAs prove a fresh main; anything malformed fails closed.
    if not _same_sha(snapshot.main_sha, snapshot.observed_main_sha):
        problems.add("STALE_MAIN")
    if len(snapshot.issue_ids) != len(set(snapshot.issue_ids)):
        problems.add("DUPLICATE_ISSUE")
    if len(snapshot.next_ids) != len(set(snapshot.next_ids)):
        problems.add("DUPLICATE_NEXT")
    known = set(snapshot.issue_ids)
    if any(issue not in known for issue in snapshot.next_ids):
        problems.add("ORPHAN_NEXT")
    if any(issue not in known for _, issue in snapshot.pr_issue_bindings):
        problems.add("ORPHAN_PR")
    if any(issue not in known for issue in snapshot.active_lease_issue_ids):
        problems.add("ORPHAN_LEASE")
    bound = [issue for _, issue in snapshot.pr_issue_bindings]
    pr_numbers = [pr for pr, _ in snapshot.pr_issue_bindings]
    if len(bound) != len(set(bound)) or len(pr_numbers) != len(set(pr_numbers)):
        problems.add("DUPLICATE_PR_BINDING")
    if len(snapshot.active_lease_issue_ids) != len(set(snapshot.active_lease_issue_ids)):
        problems.add("DUPLICATE_LEASE")
    active = set(snapshot.active_lease_issue_ids).union(bound)
    if active.intersection(snapshot.next_ids):
        problems.add("ACTIVE_WORK_IN_NEXT")
    retired = set(snapshot.retired_pilot_issue_ids)
    if retired.intersection(snapshot.next_ids) or retired.intersection(active):
        problems.add("RETIRED_PILOT_REACTIVATED")
    return tuple(sorted(problems))


@dataclass(frozen=True)
class PullRequestObservation:
    """Live read-only facts about one open PR, as fetched by a trusted caller.

    ``recorded_head_sha`` is the head the writer/ledger last recorded; the
    ``*_head_sha`` / ``*_base_sha`` review/CI fields are the exact head and
    base those results were produced on. Evidence counts only when both match
    the live head and live main, so a base advance invalidates it even when
    the head is unchanged.
    """
    pr: int
    issue: int
    recorded_head_sha: str
    observed_head_sha: str
    base_sha: str
    approved_head_sha: str | None = None
    approved_base_sha: str | None = None
    ci_head_sha: str | None = None
    ci_base_sha: str | None = None
    ci_conclusion: str | None = None
    merge_ready_claimed: bool = False


def _valid_sha(value: str | None) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _same_sha(left: str | None, right: str | None) -> bool:
    """Malformed or empty SHAs never compare equal (fail closed)."""
    return _valid_sha(left) and _valid_sha(right) and left == right


def pr_inconsistencies(
    snapshot: WorkSnapshot, observations: tuple[PullRequestObservation, ...]
) -> tuple[tuple[int, str], ...]:
    """Return stable sorted ``(pr, FINDING)`` pairs for exact-head PR truth.

    Approval and CI only count for the live head; nothing here grants
    merge, review or lease authority.
    """
    problems: set[tuple[int, str]] = set()
    bindings = set(snapshot.pr_issue_bindings)
    seen: set[int] = set()
    for obs in observations:
        pr_ref = obs.pr if _valid_work_id(obs.pr) else 0
        if not _valid_work_id(obs.pr):
            problems.add((pr_ref, "INVALID_PR_ID"))
        if not _valid_work_id(obs.issue):
            problems.add((pr_ref, "INVALID_ISSUE_ID"))
        # Invalid identities must not enter duplicate tracking: True == 1
        # and 9.0 == 9 in Python, but neither is a valid PR identifier.
        if _valid_work_id(obs.pr):
            if obs.pr in seen:
                problems.add((pr_ref, "DUPLICATE_PR_OBSERVATION"))
            seen.add(obs.pr)
        if (obs.pr, obs.issue) not in bindings:
            problems.add((pr_ref, "PR_BINDING_MISMATCH"))
        if not all(_valid_sha(v) for v in (obs.recorded_head_sha, obs.observed_head_sha, obs.base_sha)):
            problems.add((pr_ref, "INVALID_SHA"))
        head = obs.observed_head_sha
        head_current = _same_sha(obs.recorded_head_sha, head)
        if not head_current:
            problems.add((pr_ref, "STALE_PR_HEAD"))
        live_main = snapshot.observed_main_sha
        base_current = _same_sha(obs.base_sha, live_main)
        if not base_current:
            problems.add((pr_ref, "BASE_BEHIND_MAIN"))
        approved = _same_sha(obs.approved_head_sha, head) and _same_sha(obs.approved_base_sha, live_main)
        if (obs.approved_head_sha is not None or obs.approved_base_sha is not None) and not approved:
            problems.add((pr_ref, "STALE_APPROVAL"))
        ci_on_head = _same_sha(obs.ci_head_sha, head) and _same_sha(obs.ci_base_sha, live_main)
        if (obs.ci_head_sha is not None or obs.ci_base_sha is not None) and not ci_on_head:
            problems.add((pr_ref, "STALE_CI"))
        ci_green = ci_on_head and obs.ci_conclusion == "success"
        if ci_on_head and not ci_green:
            problems.add((pr_ref, "CI_NOT_GREEN"))
        if obs.merge_ready_claimed and not (head_current and base_current and approved and ci_green):
            problems.add((pr_ref, "UNSUPPORTED_MERGE_READY"))
    return tuple(sorted(problems))
