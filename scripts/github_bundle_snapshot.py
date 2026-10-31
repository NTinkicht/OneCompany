"""Raw captured GitHub payloads -> one schema-5 reconciliation snapshot (#387).

OC-P0-01: the mappers ``github_pr_observation`` (#379), ``github_work_observation``
(#381) and ``github_required_check_observation`` (#383) and the assembler
``github_snapshot_assembly`` (#385) are pure. This pure module is the single
entry point that takes ONE JSON-able bundle of payloads a trusted fetcher
captured and routes each part to the right mapper, so no fetcher re-implements
the wiring.

The bundle must carry exactly these keys (unknown or missing keys are refused):
``observed_at`` (timezone-aware ISO-8601), ``main_sha``, ``active_lease_issue_ids``,
``retired_pilot_issue_ids``, ``write_attempts``, ``trusted_reviewers``, ``main_ref``,
``issue_pages``, ``issues_complete``, ``branch_pages``, ``branches_complete``,
``rule_pages``, ``rules_complete``, ``app_slugs`` (decimal-string app id -> slug) and
``pull_requests`` (each with ``pull``, ``issue``, ``recorded_head_sha``, optional
``ci_base_sha``, ``review_pages``, ``reviews_complete``, ``check_run_pages``,
``check_runs_complete``, ``commit_pages``, ``commits_complete``, ``thread_pages``).

Every refusal is raised as ``InvalidBundle`` naming the section only, never a
payload value. Nothing here performs a request, reads a token or reads the clock.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import github_pr_observation as prs  # noqa: E402
import github_required_check_observation as checks  # noqa: E402
import github_work_observation as work  # noqa: E402
from github_snapshot_assembly import InvalidAssembly, assemble_snapshot  # noqa: E402

EXIT_OK, EXIT_INVALID = 0, 2

_BUNDLE_KEYS = {
    "observed_at", "main_sha", "active_lease_issue_ids", "retired_pilot_issue_ids",
    "write_attempts", "trusted_reviewers", "main_ref", "issue_pages", "issues_complete",
    "branch_pages", "branches_complete", "rule_pages", "rules_complete", "app_slugs",
    "pull_requests",
}
_PR_REQUIRED = {
    "pull", "issue", "recorded_head_sha", "review_pages", "reviews_complete",
    "check_run_pages", "check_runs_complete", "commit_pages", "commits_complete",
    "thread_pages",
}
_PR_KEYS = _PR_REQUIRED | {"ci_base_sha"}


class InvalidBundle(ValueError):
    """The bundle is malformed, incomplete or rejected by a mapper."""


def _exact(obj: object, keys: set[str], required: set[str], path: str) -> dict[str, Any]:
    if type(obj) is not dict or not required <= set(obj) or not set(obj) <= keys:
        raise InvalidBundle(f"invalid {path}")
    return obj


def _flag(value: object, path: str) -> bool:
    if type(value) is not bool:
        raise InvalidBundle(f"invalid {path}")
    return value


def _observed_at(value: object) -> dt.datetime:
    if type(value) is not str:
        raise InvalidBundle("invalid observed_at")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        raise InvalidBundle("invalid observed_at") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidBundle("invalid observed_at")
    return parsed


def _app_slugs(value: object) -> dict[int, str]:
    if type(value) is not dict:
        raise InvalidBundle("invalid app_slugs")
    mapped: dict[int, str] = {}
    for key, slug in value.items():
        if type(key) is not str or not key.isascii() or not key.isdecimal() or int(key) <= 0:
            raise InvalidBundle("invalid app_slugs")
        mapped[int(key)] = slug
    return mapped


def _pull_request(record: object, path: str) -> dict[str, Any]:
    pr = _exact(record, _PR_KEYS, _PR_REQUIRED, path)
    try:
        mapped = prs.pr_observation(
            pr["pull"], issue=pr["issue"], recorded_head_sha=pr["recorded_head_sha"],
            review_pages=pr["review_pages"], reviews_complete=_flag(pr["reviews_complete"], f"{path}.reviews_complete"),
            check_run_pages=pr["check_run_pages"], check_runs_complete=_flag(pr["check_runs_complete"], f"{path}.check_runs_complete"),
            commit_pages=pr["commit_pages"], commits_complete=_flag(pr["commits_complete"], f"{path}.commits_complete"),
            thread_pages=pr["thread_pages"])
    except prs.InvalidPayload as exc:
        raise InvalidBundle(f"{path}: {exc}") from None
    if "ci_base_sha" in pr:
        if type(pr["ci_base_sha"]) is not str or not pr["ci_base_sha"]:
            raise InvalidBundle(f"invalid {path}.ci_base_sha")
        mapped = dict(mapped, ci_base_sha=pr["ci_base_sha"])
    return mapped


def snapshot_from_bundle(bundle: object) -> dict[str, Any]:
    """Return the schema-5 document, or raise InvalidBundle."""
    data = _exact(bundle, _BUNDLE_KEYS, _BUNDLE_KEYS, "bundle")
    observed_at = _observed_at(data["observed_at"])
    if type(data["pull_requests"]) is not list:
        raise InvalidBundle("invalid pull_requests")
    try:
        mapped_work = work.work_observation(
            data["main_ref"],
            issue_pages=data["issue_pages"], issues_complete=_flag(data["issues_complete"], "issues_complete"),
            branch_pages=data["branch_pages"], branches_complete=_flag(data["branches_complete"], "branches_complete"))
        required = checks.required_check_observation(
            data["rule_pages"], rules_complete=_flag(data["rules_complete"], "rules_complete"),
            app_slugs=_app_slugs(data["app_slugs"]))
    except (work.InvalidPayload, checks.InvalidPayload) as exc:
        raise InvalidBundle(str(exc)) from None
    pulls = [_pull_request(r, f"pull_requests[{i}]") for i, r in enumerate(data["pull_requests"])]
    try:
        return assemble_snapshot(
            observed_at, work=mapped_work, pull_requests=pulls, required_checks=required,
            main_sha=data["main_sha"], active_lease_issue_ids=data["active_lease_issue_ids"],
            retired_pilot_issue_ids=data["retired_pilot_issue_ids"],
            write_attempts=data["write_attempts"], trusted_reviewers=data["trusted_reviewers"])
    except InvalidAssembly as exc:
        raise InvalidBundle(str(exc)) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        snapshot = snapshot_from_bundle(json.loads(args.bundle.read_text(encoding="utf-8")))
    except InvalidBundle as exc:
        print(f"invalid bundle: {exc}", file=sys.stderr)
        return EXIT_INVALID
    except (OSError, ValueError, RecursionError):
        print("invalid bundle: unreadable or not JSON", file=sys.stderr)
        return EXIT_INVALID
    sys.stdout.write(json.dumps(snapshot, sort_keys=True, indent=2) + "\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
