"""Fail-closed, project-independent canonical Work Unit stream binding.

This guard does not acquire a lease, create a branch or assert that GitHub
state is current. It rejects local/base-trusted identity drift before
admission; the durable ledger remains the authority for concurrent claims.
"""
from __future__ import annotations

from typing import Any



def duplicate_queue_binding_violations(work_units: list[dict[str, Any]]) -> list[str]:
    """Detect two declared WUs claiming the same immutable stream identity.

    This validates a queue snapshot; it does not replace live GitHub lookup or
    durable atomic lease arbitration during unattended start.
    """
    pr_owner: dict[int, str] = {}
    branch_owner: dict[str, str] = {}
    problems: set[str] = set()
    for item in work_units:
        if not isinstance(item, dict):
            continue
        wu = item.get("id")
        if not isinstance(wu, str) or not wu:
            continue
        branch = item.get("branch")
        if isinstance(branch, str) and branch:
            previous = branch_owner.setdefault(branch, wu)
            if previous != wu:
                problems.add(
                    f"canonical branch {branch!r} shared by WUs {previous} and {wu}"
                )
        pr = item.get("pr")
        if isinstance(pr, int) and not isinstance(pr, bool) and pr > 0:
            previous = pr_owner.setdefault(pr, wu)
            if previous != wu:
                problems.add(
                    f"canonical PR #{pr} shared by WUs {previous} and {wu}"
                )
    return sorted(problems)

def binding_violations(
    work_unit: str,
    branch: str,
    pr: int | None,
    work_map: dict[str, dict[str, Any]],
    active_leases: list[dict[str, Any]],
    *,
    require_complete: bool = False,
) -> list[str]:
    """Reject attempts to rebind one WU or reuse another WU's branch/PR.

    Missing queue bindings are permitted for pre-PR *local* preparations.
    Durable acquisition separately requires the exact base-trusted PR mapping.
    """
    violations: list[str] = []
    if not isinstance(work_unit, str) or not work_unit:
        return ["invalid_work_unit_identity"]
    if not isinstance(branch, str) or not branch.strip():
        violations.append("invalid_implementation_branch")
    if pr is not None and (not isinstance(pr, int) or isinstance(pr, bool) or pr <= 0):
        violations.append("invalid_implementation_pr")
    candidate = work_map.get(work_unit)
    if not isinstance(candidate, dict):
        return [*violations, f"unknown_work_unit:{work_unit}"]

    expected_branch = candidate.get("branch")
    expected_pr = candidate.get("pr")
    if require_complete and (
        not isinstance(expected_branch, str) or not expected_branch.strip()
    ):
        violations.append(f"canonical_branch_missing:{work_unit}")
    if require_complete and (
        not isinstance(expected_pr, int)
        or isinstance(expected_pr, bool)
        or expected_pr <= 0
    ):
        violations.append(f"canonical_pr_missing:{work_unit}")
    if expected_branch is not None and expected_branch != branch:
        violations.append(
            f"canonical_branch_mismatch:{work_unit}:expected={expected_branch}"
        )
    if expected_pr is not None and expected_pr != pr:
        violations.append(f"canonical_pr_mismatch:{work_unit}:expected={expected_pr}")

    # Multiple WU -> same branch/PR is ambiguous even if the other WU has
    # already been merged: PR references are immutable stream identities.
    for other_id, other in sorted(work_map.items()):
        if other_id == work_unit or not isinstance(other, dict):
            continue
        if branch and other.get("branch") == branch:
            violations.append(f"branch_owned_by_other_wu:{other_id}")
        if pr is not None and other.get("pr") == pr:
            violations.append(f"pr_owned_by_other_wu:{other_id}")

    for lease in active_leases:
        if lease.get("role", "implementation") != "implementation":
            continue
        other_wu = lease.get("work_unit")
        if other_wu == work_unit:
            violations.append(
                "canonical_lease_already_active:"
                f"wu={work_unit}:lease={lease.get('id')}:"
                f"branch={lease.get('branch')}:pr={lease.get('pr')}"
            )
            continue
        if branch and lease.get("branch") == branch:
            violations.append(f"branch_leased_to_other_wu:{other_wu}")
        if pr is not None and lease.get("pr") == pr:
            violations.append(f"pr_leased_to_other_wu:{other_wu}")
    return sorted(set(violations))
