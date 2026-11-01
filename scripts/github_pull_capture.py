"""Single pull-request capture that refuses head or base movement (#391).

OC-P0-01: ``github_page_capture.capture_pull_pages`` needs the head SHA up
front, and nothing fetched ``GET /pulls/{n}`` itself. A fetcher that reads the
pull, then its check runs, could pair a pull body from head A with check runs
from head B when the PR is pushed mid-capture. This pure module closes that
window: it fetches the pull, captures reviews, exact-head check runs and
commits, then fetches the pull again and refuses if ``head.sha`` or
``base.sha`` moved.

The transport is injected exactly as in ``github_page_capture``. The result is
one ``pull_requests[]`` record for ``github_bundle_snapshot``. Review threads
are GraphQL and out of scope: the caller passes ``thread_pages`` (default
none, which the mapper reports as incomplete and the report fails closed on).
Refusals name the step only, never a response body. Nothing here performs a
request, reads a token or reads the clock.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

from github_page_capture import (
    DEFAULT_MAX_PAGES, CaptureError, Fetch, Response, _repo, capture_pull_pages)

_SHA = re.compile(r"[0-9a-f]{40}")


def _pull(fetch: Fetch, repo: str, number: int, step: str) -> tuple[dict[str, Any], str, str]:
    response = fetch(f"/repos/{repo}/pulls/{number}")
    if type(response) is not Response or type(response.status) is not int:
        raise CaptureError(f"invalid response for pull {step}")
    if response.status != 200:
        raise CaptureError(f"status {response.status} for pull {step}")
    body = response.body
    if type(body) is not dict or body.get("number") != number or type(body.get("number")) is not int:
        raise CaptureError(f"invalid pull {step}")
    shas = []
    for side in ("head", "base"):
        node = body.get(side)
        sha = node.get("sha") if type(node) is dict else None
        if type(sha) is not str or not _SHA.fullmatch(sha):
            raise CaptureError(f"invalid pull {step} {side}")
        shas.append(sha)
    return body, shas[0], shas[1]


def capture_pull_request(
    fetch: Fetch, repo: str, number: int, *, issue: int, recorded_head_sha: str,
    thread_pages: Sequence[Any] = (), max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    """Return one ``pull_requests[]`` bundle record, or raise CaptureError."""
    repo = _repo(repo)
    if type(number) is not int or number < 1 or type(issue) is not int or issue < 1:
        raise CaptureError("invalid pull number or issue")
    if type(recorded_head_sha) is not str or not recorded_head_sha:
        raise CaptureError("invalid recorded head sha")
    if type(thread_pages) not in (list, tuple):
        raise CaptureError("invalid thread pages")
    pull, head, base = _pull(fetch, repo, number, "before")
    pages = capture_pull_pages(fetch, repo, number, head, max_pages=max_pages)
    _, head_after, base_after = _pull(fetch, repo, number, "after")
    if head_after != head or base_after != base:
        raise CaptureError("pull head or base moved during capture")
    return {
        "pull": pull, "issue": issue, "recorded_head_sha": recorded_head_sha,
        "thread_pages": list(thread_pages), **pages,
    }
