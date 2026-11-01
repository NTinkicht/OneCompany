"""Whole-bundle capture composing the main-ref and pull-request captures (#395).

OC-P0-01: ``github_main_capture`` (#393) captures ``main_ref`` and the repo pages
and ``github_pull_capture`` (#391) captures one pull request, but nothing composed
them into the exact bundle ``github_bundle_snapshot`` (#387) consumes. A caller that
wires them by hand can read the pull requests after ``main`` moved past the
``main_ref`` it recorded, so the bundle would describe two different ``main`` states.

This pure module composes them. The transport is injected exactly as in the other
captures. It captures ``main_ref`` and the repo pages, then each requested pull request
in the given order, then reads the main ref one final time and refuses if the commit
moved at any point. The caller-supplied fields (``observed_at``, ``main_sha``,
lease/pilot ids, write attempts, trusted reviewers, app slugs) are the caller's RECORDED
baseline and are copied through unchanged; ``snapshot_from_bundle`` validates them.
The result has exactly the bundle keys. Refusals name the step only, never a response
body. Nothing here performs a request, reads a token or reads the clock.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from github_main_capture import _main, capture_main
from github_page_capture import DEFAULT_MAX_PAGES, CaptureError, Fetch, _repo
from github_pull_capture import capture_pull_request

MAX_PULLS = 100
_PULL_KEYS = {"number", "issue", "recorded_head_sha", "thread_pages", "ci_base_sha"}
_PULL_REQUIRED = {"number", "issue", "recorded_head_sha"}


def _spec(spec: object) -> Mapping[str, Any]:
    if type(spec) is not dict or not _PULL_REQUIRED <= set(spec) <= _PULL_KEYS:
        raise CaptureError("invalid pull spec")
    return spec


def capture_bundle(
    fetch: Fetch, repo: str, pulls: Sequence[Mapping[str, Any]], *, observed_at: str,
    main_sha: str, active_lease_issue_ids: Sequence[int], retired_pilot_issue_ids: Sequence[int],
    write_attempts: Sequence[Any], trusted_reviewers: Sequence[str],
    app_slugs: Mapping[str, str], max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    """Return one ``github_bundle_snapshot`` bundle, or raise CaptureError."""
    repo = _repo(repo)
    if type(pulls) is not list or len(pulls) > MAX_PULLS:
        raise CaptureError("invalid pull specs")
    specs = [_spec(spec) for spec in pulls]
    numbers = [spec["number"] for spec in specs]
    if len(set(map(repr, numbers))) != len(numbers):
        raise CaptureError("duplicate pull number")
    captured = capture_main(fetch, repo, max_pages=max_pages)
    sha = captured["main_ref"]["object"]["sha"]
    records = []
    for spec in specs:
        extra = {"thread_pages": spec["thread_pages"]} if "thread_pages" in spec else {}
        record = capture_pull_request(
            fetch, repo, spec["number"], issue=spec["issue"],
            recorded_head_sha=spec["recorded_head_sha"], max_pages=max_pages, **extra)
        if "ci_base_sha" in spec:
            record["ci_base_sha"] = spec["ci_base_sha"]
        records.append(record)
    _, sha_after = _main(fetch, repo, "final")
    if sha_after != sha:
        raise CaptureError("main moved during bundle capture")
    return {
        "observed_at": observed_at, "main_sha": main_sha,
        "active_lease_issue_ids": list(active_lease_issue_ids),
        "retired_pilot_issue_ids": list(retired_pilot_issue_ids),
        "write_attempts": list(write_attempts), "trusted_reviewers": list(trusted_reviewers),
        "main_ref": captured["main_ref"], "issue_pages": captured["issue_pages"],
        "issues_complete": captured["issues_complete"], "branch_pages": captured["branch_pages"],
        "branches_complete": captured["branches_complete"], "rule_pages": captured["rule_pages"],
        "rules_complete": captured["rules_complete"], "app_slugs": dict(app_slugs),
        "pull_requests": records,
    }
