"""Read-only consistency checks for a synthetic live work snapshot.

Caller must acquire the actual GitHub and ledger data from trusted sources.
This module never claims a lease, merges, or modifies the queue.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkSnapshot:
    main_sha: str
    observed_main_sha: str
    issue_ids: tuple[int, ...]
    next_ids: tuple[int, ...]
    pr_issue_bindings: tuple[tuple[int, int], ...]
    active_lease_issue_ids: tuple[int, ...]
    retired_pilot_issue_ids: tuple[int, ...] = ()


def inconsistencies(snapshot: WorkSnapshot) -> tuple[str, ...]:
    """Return stable fail-closed findings, with no inferred permissions."""
    problems: set[str] = set()
    if not snapshot.main_sha or snapshot.main_sha != snapshot.observed_main_sha:
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
