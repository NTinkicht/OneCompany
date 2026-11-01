"""Main-ref capture that refuses ``main`` movement during page capture (#393).

OC-P0-01: ``github_page_capture`` (#389) captures issue, branch and rule pages
and ``github_pull_capture`` (#391) captures a pull request, but nothing fetched
``GET /repos/{o}/{r}/git/ref/heads/main``. A fetcher that reads the ref and
then pages the listings can pair a ``main_ref`` from commit A with listings read
after ``main`` moved to commit B. This pure module reads the ref, captures the
repo pages, reads the ref again and refuses if the commit moved.

The transport is injected exactly as in ``github_page_capture``. The result
keys equal ``github_bundle_snapshot`` bundle keys (``main_ref`` and the repo pages
with their completeness flags) so they merge unchanged.
Refusals name the step only, never a response body. Nothing here performs a
request, reads a token or reads the clock.
"""
from __future__ import annotations

import re
from typing import Any

from github_page_capture import (
    DEFAULT_MAX_PAGES, CaptureError, Fetch, Response, _repo, capture_repo_pages)

_SHA = re.compile(r"[0-9a-f]{40}")
_MAIN_REF = "refs/heads/main"


def _main(fetch: Fetch, repo: str, step: str) -> tuple[dict[str, Any], str]:
    response = fetch(f"/repos/{repo}/git/ref/heads/main")
    if type(response) is not Response or type(response.status) is not int:
        raise CaptureError(f"invalid response for main ref {step}")
    if response.status != 200:
        raise CaptureError(f"status {response.status} for main ref {step}")
    body = response.body
    target = body.get("object") if type(body) is dict else None
    if type(body) is not dict or body.get("ref") != _MAIN_REF or type(target) is not dict:
        raise CaptureError(f"invalid main ref {step}")
    sha = target.get("sha")
    if target.get("type") != "commit" or type(sha) is not str or not _SHA.fullmatch(sha):
        raise CaptureError(f"invalid main ref {step} object")
    return body, sha


def capture_main(fetch: Fetch, repo: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> dict[str, Any]:
    """Return ``main_ref`` and repo pages, or raise CaptureError.

    ``main_sha`` is deliberately not returned: it is the caller's RECORDED
    baseline, compared against the observed sha taken from ``main_ref``. Setting
    it from the live ref would hide stale-main drift.
    """
    repo = _repo(repo)
    main_ref, sha = _main(fetch, repo, "before")
    pages = capture_repo_pages(fetch, repo, max_pages=max_pages)
    _, sha_after = _main(fetch, repo, "after")
    if sha_after != sha:
        raise CaptureError("main moved during capture")
    return {"main_ref": main_ref, **pages}
