"""One fail-closed reconciliation report over a serialized live snapshot (#363).

OC-P0-01: before admitting product work, a trusted caller serializes what it
observed (main SHA, issues/NEXT/leases, PR head/review/CI evidence, pipeline
branches, recorded external writes) with the observation timestamp. This
module strictly loads that JSON, runs every read-only check in
``live_work_reconciliation`` and returns one deterministic verdict.

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

SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_SECONDS = 900
EXIT_CONSISTENT, EXIT_INCONSISTENT, EXIT_INVALID = 0, 1, 2

_TOP_KEYS = {"schema_version", "observed_at", "snapshot", "pull_requests",
             "branches", "write_attempts", "trusted_reviewers"}
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
    "approved_head_sha": (_OPT_STR, False), "approved_base_sha": (_OPT_STR, False),
    "ci_head_sha": (_OPT_STR, False), "ci_base_sha": (_OPT_STR, False),
    "ci_conclusion": (_OPT_STR, False), "merge_ready_claimed": (_BOOL, False),
    "approved_by": (_OPT_STR, False), "material_authors": ("strs", False),
}
_ATTEMPT_FIELDS = {
    "operation_id": (_STR, True), "issue": (_INT, True), "outcome": (_STR, True),
    "readback": (_OPT_STR, False), "retries": (_INT, False),
    "safety_rejected": (_BOOL, False), "expected_head_sha": (_OPT_STR, False),
    "observed_head_sha": (_OPT_STR, False), "pre_retry_readback": (_OPT_STR, False),
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
        "pull_requests": tuple(PullRequestObservation(**r) for r in
                               _records(data["pull_requests"], _PR_FIELDS, "pull_requests")),
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
    findings = {
        "snapshot": list(inconsistencies(snapshot)),
        "freshness": list(snapshot_freshness(loaded["observed_at"], now, max_age_seconds)),
        "pull_requests": [list(f) for f in pr_inconsistencies(
            snapshot, loaded["pull_requests"], trusted_reviewers=loaded["trusted_reviewers"])],
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
