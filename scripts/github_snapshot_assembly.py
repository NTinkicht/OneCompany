"""Compose the GitHub mappers into one schema-5 reconciliation snapshot (#385).

OC-P0-01: ``github_pr_observation`` (#379), ``github_work_observation`` (#381)
and ``github_required_check_observation`` (#383) each map one section of the
document that ``live_reconciliation_report.load_snapshot`` judges. This pure
module is the single place that joins them, so the sections cannot drift:

* ``snapshot.pr_issue_bindings`` is derived from the pull request records
  (``pr`` and ``issue``), never accepted from the caller;
* ``branches``, ``issue_ids``, ``next_ids``, ``ineligible_issue_ids`` and
  ``observed_main_sha`` come only from the work observation;
* caller-owned records (recorded main, leases, retired pilots, recorded
  write attempts, trusted reviewers) are passed through with type checks.

``observed_at`` must be a timezone-aware ``datetime`` (a naive time is never
live evidence). The result is round-tripped through ``load_snapshot``; any
refusal is re-raised as ``InvalidAssembly`` naming the path only, never a
value. Nothing here performs a request, reads a token or reads the clock.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from live_reconciliation_report import InvalidSnapshot, load_snapshot  # noqa: E402

_WORK_KEYS = {"observed_main_sha", "issue_ids", "next_ids",
              "ineligible_issue_ids", "branches"}


class InvalidAssembly(ValueError):
    """An input is malformed, ambiguous or rejected by the report loader."""


def _ints(value: object, path: str) -> list[int]:
    if type(value) not in (list, tuple) or not all(type(v) is int for v in value):
        raise InvalidAssembly(f"invalid {path}")
    return list(value)


def _work(work: object) -> dict[str, Any]:
    if type(work) is not dict or set(work) != _WORK_KEYS:
        raise InvalidAssembly("invalid work")
    return work


def assemble_snapshot(
    observed_at: dt.datetime,
    *,
    work: object,
    pull_requests: Sequence[object],
    required_checks: Sequence[object],
    main_sha: str,
    active_lease_issue_ids: Sequence[int],
    retired_pilot_issue_ids: Sequence[int] = (),
    write_attempts: Sequence[Mapping[str, Any]] = (),
    trusted_reviewers: Sequence[str],
) -> dict[str, Any]:
    """Return the schema-5 document, or raise InvalidAssembly."""
    if (not isinstance(observed_at, dt.datetime) or observed_at.tzinfo is None
            or observed_at.utcoffset() is None):
        raise InvalidAssembly("invalid observed_at")
    if type(main_sha) is not str:
        raise InvalidAssembly("invalid main_sha")
    mapped = _work(work)
    if type(pull_requests) not in (list, tuple):
        raise InvalidAssembly("invalid pull_requests")
    bindings: list[list[int]] = []
    seen: set[int] = set()
    for i, record in enumerate(pull_requests):
        if type(record) is not dict or type(record.get("pr")) is not int \
                or type(record.get("issue")) is not int:
            raise InvalidAssembly(f"invalid pull_requests[{i}]")
        if record["pr"] in seen:
            raise InvalidAssembly(f"duplicate pull_requests[{i}].pr")
        seen.add(record["pr"])
        bindings.append([record["pr"], record["issue"]])
    document = {
        "schema_version": 5,
        "observed_at": observed_at.isoformat(),
        "snapshot": {
            "main_sha": main_sha,
            "observed_main_sha": mapped["observed_main_sha"],
            "issue_ids": _ints(mapped["issue_ids"], "work.issue_ids"),
            "next_ids": _ints(mapped["next_ids"], "work.next_ids"),
            "pr_issue_bindings": bindings,
            "active_lease_issue_ids": _ints(active_lease_issue_ids,
                                            "active_lease_issue_ids"),
            "retired_pilot_issue_ids": _ints(retired_pilot_issue_ids,
                                             "retired_pilot_issue_ids"),
            "ineligible_issue_ids": _ints(mapped["ineligible_issue_ids"],
                                          "work.ineligible_issue_ids"),
        },
        "pull_requests": [dict(r) for r in pull_requests],
        "branches": list(mapped["branches"]) if type(mapped["branches"]) is list
        else None,
        "write_attempts": [dict(a) for a in write_attempts],
        "trusted_reviewers": list(trusted_reviewers),
        "required_checks": [dict(c) for c in required_checks],
    }
    try:
        load_snapshot(document)
    except (InvalidSnapshot, TypeError) as exc:
        raise InvalidAssembly(str(exc)) from None
    return document
