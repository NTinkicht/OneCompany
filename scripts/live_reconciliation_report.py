"""One fail-closed reconciliation report over a serialized live snapshot (#363).

OC-P0-01: before admitting product work, a trusted caller serializes what it
observed (main SHA, issues/NEXT/leases, PR head/review/CI evidence, pipeline
branches, recorded external writes) with the observation timestamp. This
module strictly loads that JSON, runs every read-only check in
``live_work_reconciliation`` and returns one deterministic verdict.

Schema 2 (#367): each pull request's CI is never taken from the caller. It is
derived from the exact-head required check runs the caller fetched, through
``required_check_reconciliation.aggregate_required_checks``.

Schema 3 (#371): each pull request's approval (head, base, reviewer) is never
taken from the caller either. It is derived from the raw reviews the caller
fetched, through ``review_approval_reconciliation.attribute_approval``;
``pr_inconsistencies`` still judges base freshness and author independence.

Schema 4 (#375): each pull request's material authors are never taken from
the caller. They are derived from the exact-head commit list the caller
fetched, through ``material_authorship_reconciliation.derive_material_authors``;
any ambiguity withholds them, so ``pr_inconsistencies`` refuses the approval.

``CONSISTENT`` only when every check is empty and the snapshot is fresh; any
finding is ``INCONSISTENT``; malformed input is refused (never coerced).
Nothing here fetches, claims a lease, mutates the queue or retries a write.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from live_work_reconciliation import (  # noqa: E402
    PullRequestObservation,
    WorkSnapshot,
    WriteAttempt,
    branch_inconsistencies,
    inconsistencies,
    pr_inconsistencies,
    replay_inconsistencies,
    snapshot_freshness,
)
from material_authorship_reconciliation import (  # noqa: E402
    CommitObservation,
    derive_material_authors,
)
from review_approval_reconciliation import (  # noqa: E402
    ReviewObservation,
    attribute_approval,
)
from required_check_reconciliation import (  # noqa: E402
    CheckRunObservation,
    RequiredCheck,
    aggregate_required_checks,
)

SCHEMA_VERSION = 4
DEFAULT_MAX_AGE_SECONDS = 900
EXIT_CONSISTENT, EXIT_INCONSISTENT, EXIT_INVALID = 0, 1, 2

_TOP_KEYS = {"schema_version", "observed_at", "snapshot", "pull_requests",
             "branches", "write_attempts", "trusted_reviewers", "required_checks"}
_INT, _STR, _BOOL, _OPT_STR = "int", "str", "bool", "str|null"
_SNAPSHOT_FIELDS = {
    "main_sha": (_STR, True), "observed_main_sha": (_STR, True),
    "issue_ids": ("ints", True), "next_ids": ("ints", True),
    "pr_issue_bindings": ("pairs", True), "active_lease_issue_ids": ("ints", True),
    "retired_pilot_issue_ids": ("ints", False), "ineligible_issue_ids": ("ints", False),
}
_PR_FIELDS = {
    "pr": (_INT, True), "issue": (_INT, True), "recorded_head_sha": (_STR, True),
    "observed_head_sha": (_STR, True), "base_sha": (_STR, True),
    # ci_head_sha / ci_conclusion are derived from check_runs, and
    # approved_head_sha / approved_base_sha / approved_by from reviews,
    # and material_authors from commits; none of them is accepted from the
    # caller.
    "ci_base_sha": (_OPT_STR, False), "check_runs": ("records", True),
    "reviews": ("records", True), "commits": ("records", True),
    "merge_ready_claimed": (_BOOL, False),
}
_COMMIT_FIELDS = {
    "sha": (_STR, True), "author_login": (_OPT_STR, True),
    "committer_login": (_OPT_STR, True), "message": (_STR, True),
}
_REVIEW_FIELDS = {
    "id": (_INT, True), "reviewer": (_STR, True), "state": (_STR, True),
    "commit_id": (_STR, True), "body": (_STR, True),
}
_REQUIRED_CHECK_FIELDS = {"name": (_STR, True), "app": (_STR, True)}
_CHECK_RUN_FIELDS = {
    "id": (_INT, True), "name": (_STR, True), "app": (_STR, True),
    "head_sha": (_STR, True), "status": (_STR, True), "conclusion": (_OPT_STR, True),
}
_ATTEMPT_FIELDS = {
    "operation_id": (_STR, True), "issue": (_INT, True), "outcome": (_STR, True),
    "readback": (_OPT_STR, False), "retries": (_INT, False),
    "safety_rejected": (_BOOL, False), "expected_head_sha": (_OPT_STR, False),
    "observed_head_sha": (_OPT_STR, False), "pre_retry_readback": (_OPT_STR, False),
}


_NESTED = {
    "check_runs": (_CHECK_RUN_FIELDS, CheckRunObservation),
    "reviews": (_REVIEW_FIELDS, ReviewObservation),
    "commits": (_COMMIT_FIELDS, CommitObservation),
}


class InvalidSnapshot(ValueError):
    """The serialized snapshot does not match the schema. The message names
    only the schema path, never an input value."""


def _is_int(value: object) -> bool:
    return type(value) is int  # a JSON boolean is never an id


def _check(kind: str, value: object, path: str) -> Any:
    if kind == _INT and _is_int(value):
        return value
    if kind == _STR and type(value) is str:
        return value
    if kind == _OPT_STR and (value is None or type(value) is str):
        return value
    if kind == _BOOL and type(value) is bool:
        return value
    if kind == "ints" and type(value) is list and all(_is_int(v) for v in value):
        return tuple(value)
    if kind == "strs" and type(value) is list and all(type(v) is str for v in value):
        return tuple(value)
    if kind == "pairs" and type(value) is list and all(
            type(p) is list and len(p) == 2 and all(_is_int(v) for v in p) for p in value):
        return tuple((p[0], p[1]) for p in value)
    raise InvalidSnapshot(f"invalid {path}")


def _record(obj: object, fields: dict[str, tuple[str, bool]], path: str) -> dict[str, Any]:
    if type(obj) is not dict:
        raise InvalidSnapshot(f"invalid {path}")
    unknown = sorted(set(obj) - set(fields))
    if unknown:
        raise InvalidSnapshot(f"unknown key in {path}")
    out: dict[str, Any] = {}
    for name, (kind, required) in fields.items():
        if name not in obj:
            if required:
                raise InvalidSnapshot(f"missing {path}.{name}")
            continue
        if kind == "records":  # nested records: check_runs, reviews and commits only
            nested, factory = _NESTED[name]
            out[name] = tuple(factory(**r) for r in
                              _records(obj[name], nested, f"{path}.{name}"))
        else:
            out[name] = _check(kind, obj[name], f"{path}.{name}")
    return out


def _records(value: object, fields: dict[str, tuple[str, bool]], path: str) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise InvalidSnapshot(f"invalid {path}")
    return [_record(item, fields, f"{path}[{i}]") for i, item in enumerate(value)]


def _timestamp(value: object, path: str) -> dt.datetime:
    if type(value) is not str:
        raise InvalidSnapshot(f"invalid {path}")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        raise InvalidSnapshot(f"invalid {path}") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidSnapshot(f"invalid {path}")  # naive time is never live evidence
    return parsed


def load_snapshot(data: object) -> dict[str, Any]:
    """Strictly convert parsed JSON into the check inputs, or raise InvalidSnapshot."""
    if type(data) is not dict:
        raise InvalidSnapshot("invalid document")
    if set(data) != _TOP_KEYS:
        raise InvalidSnapshot("missing or unknown top-level key")
    if not _is_int(data["schema_version"]) or data["schema_version"] != SCHEMA_VERSION:
        raise InvalidSnapshot("unsupported schema_version")
    return {
        "observed_at": _timestamp(data["observed_at"], "observed_at"),
        "snapshot": WorkSnapshot(**_record(data["snapshot"], _SNAPSHOT_FIELDS, "snapshot")),
        "pull_requests": tuple(_records(data["pull_requests"], _PR_FIELDS, "pull_requests")),
        "required_checks": tuple(RequiredCheck(**r) for r in
                                 _records(data["required_checks"], _REQUIRED_CHECK_FIELDS,
                                          "required_checks")),
        "branches": _check("strs", data["branches"], "branches"),
        "write_attempts": tuple(WriteAttempt(**r) for r in
                                _records(data["write_attempts"], _ATTEMPT_FIELDS, "write_attempts")),
        "trusted_reviewers": _check("strs", data["trusted_reviewers"], "trusted_reviewers"),
    }


def build_report(data: object, now: dt.datetime,
                 max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS) -> dict[str, Any]:
    """Run every check over one snapshot and return a deterministic verdict."""
    loaded = load_snapshot(data)
    snapshot: WorkSnapshot = loaded["snapshot"]
    observations, check_findings, review_findings, commit_findings = [], [], [], []
    for record in loaded["pull_requests"]:
        fields = dict(record)
        runs = fields.pop("check_runs")
        reviews = fields.pop("reviews")
        commits = fields.pop("commits")
        ci = aggregate_required_checks(loaded["required_checks"], runs,
                                       fields["observed_head_sha"])
        approval = attribute_approval(reviews, fields["observed_head_sha"],
                                      loaded["trusted_reviewers"])
        authorship = derive_material_authors(commits, fields["observed_head_sha"])
        observations.append(PullRequestObservation(
            **fields, ci_head_sha=ci.ci_head_sha, ci_conclusion=ci.ci_conclusion,
            approved_head_sha=approval.approved_head_sha,
            approved_base_sha=approval.approved_base_sha,
            approved_by=approval.approved_by,
            material_authors=authorship.authors))
        check_findings.extend([fields["pr"], name, finding] for name, finding in ci.findings)
        review_findings.extend([fields["pr"], ref, finding] for ref, finding in approval.findings)
        commit_findings.extend([fields["pr"], ref, finding] for ref, finding in authorship.findings)
    findings = {
        "snapshot": list(inconsistencies(snapshot)),
        "freshness": list(snapshot_freshness(loaded["observed_at"], now, max_age_seconds)),
        "pull_requests": [list(f) for f in pr_inconsistencies(
            snapshot, tuple(observations), trusted_reviewers=loaded["trusted_reviewers"])],
        "required_checks": sorted(check_findings),
        "reviews": sorted(review_findings),
        "commits": sorted(commit_findings),
        "branches": [list(f) for f in branch_inconsistencies(snapshot, loaded["branches"])],
        "write_attempts": [list(f) for f in replay_inconsistencies(snapshot, loaded["write_attempts"])],
    }
    consistent = not any(findings.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "CONSISTENT" if consistent else "INCONSISTENT",
        "main_sha": snapshot.main_sha,
        "observed_main_sha": snapshot.observed_main_sha,
        "observed_at": loaded["observed_at"].isoformat(),
        "checked_at": now.isoformat(),
        "max_age_seconds": max_age_seconds,
        "findings": findings,
    }


def render(report: dict[str, Any]) -> str:
    return json.dumps(report, sort_keys=True, indent=2) + "\n"


def main(argv: list[str] | None = None, now: dt.datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS)
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.snapshot.read_text(encoding="utf-8"))
        report = build_report(data, now or dt.datetime.now(dt.timezone.utc), args.max_age_seconds)
    except InvalidSnapshot as exc:
        print(f"invalid snapshot: {exc}", file=sys.stderr)
        return EXIT_INVALID
    except (OSError, ValueError, RecursionError):
        # Unreadable, not UTF-8, not JSON, or beyond the parser's limits.
        print("invalid snapshot: unreadable or not JSON", file=sys.stderr)
        return EXIT_INVALID
    sys.stdout.write(render(report))
    return EXIT_CONSISTENT if report["status"] == "CONSISTENT" else EXIT_INCONSISTENT


if __name__ == "__main__":
    raise SystemExit(main())
