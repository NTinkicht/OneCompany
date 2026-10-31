"""Map raw GitHub payloads for one pull request to a schema-5 observation (#379).

OC-P0-01: ``live_reconciliation_report`` judges a serialized snapshot that a
trusted caller built. This pure module is the only place that turns the raw
GitHub response bodies the caller already fetched into one
``pull_requests[]`` record, so field drift (another head, a truncated page, a
missing app) is refused here instead of being hand-mapped into a
``CONSISTENT`` verdict.

Inputs, exactly as GitHub returns them:

* ``pull``: ``GET /repos/{o}/{r}/pulls/{n}``;
* ``review_pages``: pages of ``GET .../pulls/{n}/reviews`` (lists);
* ``check_run_pages``: pages of ``GET .../commits/{head}/check-runs``
  (objects with ``total_count`` and ``check_runs``);
* ``commit_pages``: pages of ``GET .../pulls/{n}/commits`` (lists);
* ``thread_pages``: pages of the GraphQL ``pullRequest.reviewThreads``
  connection (objects with ``nodes`` and ``pageInfo.hasNextPage``).

REST list pages carry no end marker in their body, so the caller states
whether it followed the ``Link`` header to the last page; an incomplete
review, check-run or commit listing is refused, never partially mapped.
Check runs must also add up to their ``total_count``. Review threads may be
incomplete: that is reported as ``review_threads_complete: false`` and the
report then fails closed with ``REVIEW_THREADS_INCOMPLETE``.

Nothing is coerced or defaulted. Errors name the payload path only, never a
value. Nothing here performs a request or reads a token.
"""
from __future__ import annotations

from typing import Any, Sequence


class InvalidPayload(ValueError):
    """A GitHub payload is missing a field, has the wrong type or is incomplete."""


def _get(obj: object, key: str, path: str) -> Any:
    if type(obj) is not dict or key not in obj:
        raise InvalidPayload(f"missing {path}.{key}")
    return obj[key]


def _str(obj: object, key: str, path: str) -> str:
    value = _get(obj, key, path)
    if type(value) is not str or not value:
        raise InvalidPayload(f"invalid {path}.{key}")
    return value


def _opt_str(obj: object, key: str, path: str) -> str | None:
    value = _get(obj, key, path)
    if value is not None and (type(value) is not str or not value):
        raise InvalidPayload(f"invalid {path}.{key}")
    return value


def _int(obj: object, key: str, path: str) -> int:
    value = _get(obj, key, path)
    if type(value) is not int or value < 0:  # a JSON boolean is never an id
        raise InvalidPayload(f"invalid {path}.{key}")
    return value


def _bool(obj: object, key: str, path: str) -> bool:
    value = _get(obj, key, path)
    if type(value) is not bool:
        raise InvalidPayload(f"invalid {path}.{key}")
    return value


def _login(obj: object, key: str, path: str) -> str | None:
    """A commit's GitHub user may be null (no linked account); never guessed."""
    user = _get(obj, key, path)
    if user is None:
        return None
    return _str(user, "login", f"{path}.{key}")


def _rest_items(pages: object, complete: object, path: str) -> list[Any]:
    if type(complete) is not bool:
        raise InvalidPayload(f"invalid {path} completeness")
    if not complete:
        raise InvalidPayload(f"incomplete {path}")
    if type(pages) not in (list, tuple):
        raise InvalidPayload(f"invalid {path}")
    items: list[Any] = []
    for index, page in enumerate(pages):
        if type(page) is not list:
            raise InvalidPayload(f"invalid {path}[{index}]")
        items.extend(page)
    return items


def _unique(records: list[dict[str, Any]], key: str, path: str) -> list[dict[str, Any]]:
    seen = set()
    for record in records:
        if record[key] in seen:
            raise InvalidPayload(f"duplicate {path}.{key}")
        seen.add(record[key])
    return records


def _reviews(pages: object, complete: object) -> list[dict[str, Any]]:
    out = []
    for i, raw in enumerate(_rest_items(pages, complete, "reviews")):
        path = f"reviews[{i}]"
        out.append({
            "id": _int(raw, "id", path),
            "reviewer": _str(_get(raw, "user", path), "login", f"{path}.user"),
            "state": _str(raw, "state", path),
            "commit_id": _str(raw, "commit_id", path),
            "body": _body(raw, path),
        })
    return sorted(_unique(out, "id", "reviews"), key=lambda r: r["id"])


def _body(raw: object, path: str) -> str:
    value = _get(raw, "body", path)
    if type(value) is not str:  # an empty review body is a real, empty body
        raise InvalidPayload(f"invalid {path}.body")
    return value


def _check_runs(pages: object, complete: object) -> list[dict[str, Any]]:
    if type(complete) is not bool:
        raise InvalidPayload("invalid check_runs completeness")
    if not complete:
        raise InvalidPayload("incomplete check_runs")
    if type(pages) not in (list, tuple) or not pages:
        raise InvalidPayload("invalid check_runs")
    totals, items = set(), []
    for index, page in enumerate(pages):
        path = f"check_runs[{index}]"
        totals.add(_int(page, "total_count", path))
        runs = _get(page, "check_runs", path)
        if type(runs) is not list:
            raise InvalidPayload(f"invalid {path}.check_runs")
        items.extend(runs)
    if len(totals) != 1 or totals.pop() != len(items):
        raise InvalidPayload("incomplete check_runs")
    out = []
    for i, raw in enumerate(items):
        path = f"check_runs[{i}]"
        out.append({
            "id": _int(raw, "id", path),
            "name": _str(raw, "name", path),
            "app": _str(_get(raw, "app", path), "slug", f"{path}.app"),
            "head_sha": _str(raw, "head_sha", path),
            "status": _str(raw, "status", path),
            "conclusion": _opt_str(raw, "conclusion", path),
        })
    return sorted(_unique(out, "id", "check_runs"), key=lambda r: r["id"])


def _commits(pages: object, complete: object) -> list[dict[str, Any]]:
    out = []
    for i, raw in enumerate(_rest_items(pages, complete, "commits")):
        path = f"commits[{i}]"
        out.append({
            "sha": _str(raw, "sha", path),
            "author_login": _login(raw, "author", path),
            "committer_login": _login(raw, "committer", path),
            "message": _str(_get(raw, "commit", path), "message", f"{path}.commit"),
        })
    return _unique(out, "sha", "commits")  # GitHub's order (oldest first) is kept


def _threads(pages: object) -> tuple[list[dict[str, Any]], bool]:
    if type(pages) not in (list, tuple):
        raise InvalidPayload("invalid review_threads")
    out, complete = [], False
    for index, page in enumerate(pages):
        path = f"review_threads[{index}]"
        nodes = _get(page, "nodes", path)
        if type(nodes) is not list:
            raise InvalidPayload(f"invalid {path}.nodes")
        has_next = _bool(_get(page, "pageInfo", path), "hasNextPage", f"{path}.pageInfo")
        if complete:  # a page after the declared last page is never trusted
            raise InvalidPayload(f"invalid {path} after last page")
        complete = not has_next
        for j, raw in enumerate(nodes):
            node = f"{path}.nodes[{j}]"
            out.append({
                "id": _str(raw, "id", node),
                "is_resolved": _bool(raw, "isResolved", node),
                "is_outdated": _bool(raw, "isOutdated", node),
            })
    return sorted(_unique(out, "id", "review_threads"), key=lambda r: r["id"]), complete


def pr_observation(
    pull: object,
    *,
    issue: int,
    recorded_head_sha: str,
    review_pages: Sequence[object],
    reviews_complete: bool,
    check_run_pages: Sequence[object],
    check_runs_complete: bool,
    commit_pages: Sequence[object],
    commits_complete: bool,
    thread_pages: Sequence[object],
) -> dict[str, Any]:
    """Return one schema-5 ``pull_requests`` record, or raise InvalidPayload.

    ``issue`` and ``recorded_head_sha`` come from the caller's own records
    (queue binding and recorded head), not from GitHub. ``ci_base_sha`` and
    ``merge_ready_claimed`` are claims the caller adds separately, if at all.
    """
    if type(issue) is not int or issue <= 0:
        raise InvalidPayload("invalid issue")
    if type(recorded_head_sha) is not str or not recorded_head_sha:
        raise InvalidPayload("invalid recorded_head_sha")
    number = _int(pull, "number", "pull")
    head = _str(_get(pull, "head", "pull"), "sha", "pull.head")
    base = _str(_get(pull, "base", "pull"), "sha", "pull.base")
    threads, threads_complete = _threads(thread_pages)
    return {
        "pr": number,
        "issue": issue,
        "recorded_head_sha": recorded_head_sha,
        "observed_head_sha": head,
        "base_sha": base,
        "check_runs": _check_runs(check_run_pages, check_runs_complete),
        "reviews": _reviews(review_pages, reviews_complete),
        "commits": _commits(commit_pages, commits_complete),
        "review_threads": threads,
        "review_threads_complete": threads_complete,
    }
