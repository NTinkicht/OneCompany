"""Fail-closed aggregation of required check runs on an exact PR head (#365).

OC-P0-01: ``PullRequestObservation`` carries one ``ci_head_sha`` /
``ci_conclusion`` pair. This module derives that pair from the individual
check runs a trusted caller fetched, instead of trusting a pre-aggregated
status. A required check counts only when its latest run (highest id) on the
exact head, posted by the expected app, completed with ``success``.

Read-only and pure: nothing here fetches, re-runs, dispatches or merges.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SHA = re.compile(r"[0-9a-f]{40}")
_STATUSES = frozenset({"queued", "in_progress", "completed", "waiting", "requested", "pending"})

SUCCESS, PENDING, FAILURE = "success", "pending", "failure"


@dataclass(frozen=True)
class RequiredCheck:
    """A required status check name and the app slug expected to post it."""
    name: str
    app: str


@dataclass(frozen=True)
class CheckRunObservation:
    """One check run as fetched by the trusted caller."""
    id: int
    name: str
    app: str
    head_sha: str
    status: str
    conclusion: str | None = None


@dataclass(frozen=True)
class CiAggregate:
    ci_head_sha: str | None
    ci_conclusion: str
    findings: tuple[tuple[str, str], ...]


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _valid_run(run: object) -> bool:
    if not isinstance(run, CheckRunObservation):
        return False
    if type(run.id) is not int or run.id <= 0:  # a bool is never an id
        return False
    if not (_text(run.name) and _text(run.app) and _valid_sha(run.head_sha)):
        return False
    if run.status not in _STATUSES:
        return False
    if run.status == "completed":
        return _text(run.conclusion)
    return run.conclusion is None


def aggregate_required_checks(
    required: tuple[RequiredCheck, ...],
    runs: tuple[CheckRunObservation, ...],
    head_sha: str,
) -> CiAggregate:
    """Return the exact-head CI aggregate with stable sorted findings.

    ``success`` only when every required check's latest exact-head run from
    its expected app completed ``success`` and there is no finding at all.
    Any failed, foreign or malformed input is ``failure``; otherwise a
    missing or unfinished required check is ``pending``. Only ``success``
    passes: ``neutral``, ``skipped``, ``cancelled`` and every other
    conclusion fail closed.
    """
    findings: set[tuple[str, str]] = set()
    failed = False
    head_ok = _valid_sha(head_sha)
    if not head_ok:
        findings.add(("", "INVALID_SHA"))
        failed = True

    valid_required = isinstance(required, tuple) and all(
        isinstance(r, RequiredCheck) and _text(r.name) and _text(r.app) for r in required)
    names = [r.name for r in required] if valid_required else []
    if not valid_required or len(names) != len(set(names)):
        findings.add(("", "INVALID_REQUIRED_CHECKS"))
        failed = True
    elif not required:
        findings.add(("", "NO_REQUIRED_CHECKS"))
        failed = True

    run_list = runs if isinstance(runs, tuple) else ()
    if not isinstance(runs, tuple):
        findings.add(("", "INVALID_CHECK_RUN"))
        failed = True
    valid_runs = []
    seen_ids: set[int] = set()
    for run in run_list:
        if not _valid_run(run) or run.id in seen_ids:
            findings.add((run.name if isinstance(run, CheckRunObservation) and _text(run.name) else "",
                          "INVALID_CHECK_RUN"))
            failed = True
            continue
        seen_ids.add(run.id)
        valid_runs.append(run)

    for check in (required if valid_required else ()):
        on_head = [r for r in valid_runs if r.name == check.name and r.head_sha == head_sha]
        if any(r.app != check.app for r in on_head):
            # Another app posted the required name on this head: spoofing
            # risk, never satisfied by the expected app's run alongside it.
            findings.add((check.name, "FOREIGN_APP_CHECK"))
            failed = True
        own = [r for r in on_head if r.app == check.app]
        if not own:
            findings.add((check.name, "MISSING_REQUIRED_CHECK"))
            continue
        latest = max(own, key=lambda r: r.id)
        if latest.status != "completed":
            findings.add((check.name, "PENDING_REQUIRED_CHECK"))
        elif latest.conclusion != SUCCESS:
            findings.add((check.name, "FAILED_REQUIRED_CHECK"))
            failed = True

    if failed:
        conclusion = FAILURE
    elif findings:
        conclusion = PENDING
    else:
        conclusion = SUCCESS
    return CiAggregate(head_sha if head_ok else None, conclusion, tuple(sorted(findings)))
