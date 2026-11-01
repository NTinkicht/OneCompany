"""Paginated GitHub page capture with honest completeness flags (#389).

OC-P0-01: the mappers (#379/#381/#383) refuse an incomplete listing but rely on
the caller to say whether it followed the ``Link`` header to the last page, and
``github_bundle_snapshot`` (#387) consumes those ``*_pages`` / ``*_complete``
fields. This pure module produces them, so no fetcher re-implements pagination
(where a truncated listing silently becomes ``complete=True``).

The transport is injected: ``fetch(path) -> Response(status, body, link)`` where
``path`` is an API path such as ``/repos/o/r/issues?state=open&per_page=100`` and
``link`` is the raw ``Link`` response header or ``None``. Nothing here performs a
request, reads a token or reads the clock.

Rules, all fail closed:

* only HTTP 200 is accepted; the refusal names the status and page number, never a
  response body;
* the body must be a list (or an object for the check-runs endpoint);
* a ``rel="next"`` link must point to the same endpoint path on ``api.github.com``
  (or be a bare path), with no fragment and no query key beyond those of the first
  request plus ``page``; anything else (another host, another endpoint, an extra
  parameter) is refused, so a crafted ``Link`` cannot redirect a credentialed
  fetcher elsewhere;
* a repeated next link is a loop and is refused;
* reaching ``max_pages`` with a next link still pending yields ``complete=False``
  and is never reported as complete.

The result keys equal the ``github_bundle_snapshot`` bundle keys, so they merge
into a bundle unchanged. GraphQL review threads are a separate slice.
"""
from __future__ import annotations

import re
from typing import Any, Callable, NamedTuple
from urllib.parse import parse_qsl, urlsplit

API_HOST = "api.github.com"
DEFAULT_MAX_PAGES = 50
_PER_PAGE = "per_page=100"
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
_SHA = re.compile(r"[0-9a-f]{40}")
_LINK_ENTRY = re.compile(r'<([^<>]*)>((?:\s*;\s*[A-Za-z]+\s*=\s*(?:"[^"]*"|[^\s;,]+))*)')
_REL_NEXT = re.compile(r';\s*rel\s*=\s*"?([^";,]*)"?', re.IGNORECASE)


class CaptureError(ValueError):
    """The transport answered something this module refuses to treat as a page."""


class Response(NamedTuple):
    status: int
    body: object
    link: str | None


Fetch = Callable[[str], Response]


def next_path(link: object, endpoint: str, allowed_keys: frozenset[str]) -> str | None:
    """Return the validated ``rel="next"`` path with query, or None if absent."""
    if link is None:
        return None
    if type(link) is not str:
        raise CaptureError("invalid Link header")
    found: list[str] = []
    for url, params in _LINK_ENTRY.findall(link):
        rels = _REL_NEXT.findall(params)
        if any("next" in rel.lower().split() for rel in rels):
            found.append(url)
    if not found:
        return None
    if len(found) != 1:
        raise CaptureError("ambiguous next link")
    parts = urlsplit(found[0])
    if parts.fragment or parts.username or parts.password:
        raise CaptureError("refused next link")
    if parts.scheme or parts.netloc:
        if parts.scheme != "https" or parts.netloc != API_HOST:
            raise CaptureError("refused next link host")
    if parts.path != endpoint:
        raise CaptureError("refused next link endpoint")
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if any(key not in allowed_keys for key, _ in pairs) or len({k for k, _ in pairs}) != len(pairs):
        raise CaptureError("refused next link query")
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def collect_pages(
    fetch: Fetch, path: str, *, expect: type = list, max_pages: int = DEFAULT_MAX_PAGES
) -> tuple[list[Any], bool]:
    """Follow ``Link: rel="next"`` from ``path``; return ``(pages, complete)``."""
    if type(max_pages) is not int or max_pages < 1:
        raise CaptureError("invalid max_pages")
    if expect not in (list, dict):
        raise CaptureError("invalid expected body type")
    first = urlsplit(path)
    if first.scheme or first.netloc or not first.path.startswith("/"):
        raise CaptureError("invalid path")
    allowed = frozenset(key for key, _ in parse_qsl(first.query, keep_blank_values=True)) | {"page"}
    pages: list[Any] = []
    seen: set[str] = set()
    current: str | None = path
    while current is not None:
        if current in seen:
            raise CaptureError("pagination loop")
        seen.add(current)
        if len(pages) == max_pages:
            return pages, False
        response = fetch(current)
        index = len(pages)
        if type(response) is not Response or type(response.status) is not int:
            raise CaptureError(f"invalid response on page {index}")
        if response.status != 200:
            raise CaptureError(f"status {response.status} on page {index}")
        if type(response.body) is not expect:
            raise CaptureError(f"invalid body on page {index}")
        pages.append(response.body)
        current = next_path(response.link, first.path, allowed)
    return pages, True


def _repo(repo: object) -> str:
    if type(repo) is not str or not _REPO.fullmatch(repo) or any(p in (".", "..") for p in repo.split("/")):
        raise CaptureError("invalid repo")
    return repo


def capture_repo_pages(fetch: Fetch, repo: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> dict[str, Any]:
    """Issue, branch and ``main`` rule pages with their completeness flags."""
    base = f"/repos/{_repo(repo)}"
    out: dict[str, Any] = {}
    for key, flag, suffix in (
        ("issue_pages", "issues_complete", f"/issues?state=open&{_PER_PAGE}"),
        ("branch_pages", "branches_complete", f"/branches?{_PER_PAGE}"),
        ("rule_pages", "rules_complete", f"/rules/branches/main?{_PER_PAGE}"),
    ):
        out[key], out[flag] = collect_pages(fetch, base + suffix, max_pages=max_pages)
    return out


def capture_pull_pages(
    fetch: Fetch, repo: str, number: int, head_sha: str, *, max_pages: int = DEFAULT_MAX_PAGES
) -> dict[str, Any]:
    """Review, exact-head check-run and commit pages with their completeness flags."""
    base = f"/repos/{_repo(repo)}"
    if type(number) is not int or number < 1:
        raise CaptureError("invalid pull number")
    if type(head_sha) is not str or not _SHA.fullmatch(head_sha):
        raise CaptureError("invalid head sha")
    out: dict[str, Any] = {}
    for key, flag, suffix, expect in (
        ("review_pages", "reviews_complete", f"/pulls/{number}/reviews?{_PER_PAGE}", list),
        ("check_run_pages", "check_runs_complete", f"/commits/{head_sha}/check-runs?{_PER_PAGE}", dict),
        ("commit_pages", "commits_complete", f"/pulls/{number}/commits?{_PER_PAGE}", list),
    ):
        out[key], out[flag] = collect_pages(fetch, base + suffix, expect=expect, max_pages=max_pages)
    return out
