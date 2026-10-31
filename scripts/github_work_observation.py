"""Map raw GitHub issue, branch and main-ref payloads to the snapshot work section (#381).

OC-P0-01: ``live_reconciliation_report`` judges a serialized snapshot that a
trusted caller built. ``github_pr_observation`` (#379) maps the pull request
records; this pure module maps the rest of what GitHub itself knows, so an
incorrect NEXT, a truncated issue page, a pull request counted as an issue
or a duplicate stream is refused or reported instead of being hand-mapped
into a ``CONSISTENT`` verdict.

Inputs, exactly as GitHub returns them:

* ``main_ref``: ``GET /repos/{o}/{r}/git/ref/heads/main``;
* ``issue_pages``: pages of ``GET /repos/{o}/{r}/issues?state=open`` (lists);
* ``branch_pages``: pages of ``GET /repos/{o}/{r}/branches`` (lists).

The issues endpoint also lists pull requests; an item carrying
``pull_request`` is skipped and never counted as an issue. ``next_ids`` are
open issues labelled ``l5:next``; ``ineligible_issue_ids`` are open issues
labelled ``l5:blocked``, ``l5:parked`` or ``l5:owner``. An issue with both is
reported in both, so the report raises ``INELIGIBLE_NEXT``.

REST list pages carry no end marker in their body, so the caller states
whether it followed the ``Link`` header to the last page; an incomplete
listing is refused, never partially mapped. Duplicates are refused. Nothing
is coerced or defaulted. Errors name the payload path only, never a value.

``main_sha`` (the recorded main), ``pr_issue_bindings``, leases and retired
pilots are the caller's own records and are not derived here. Nothing here
performs a request or reads a token.
"""
from __future__ import annotations

from typing import Any, Sequence

MAIN_REF = "refs/heads/main"
NEXT_LABEL = "l5:next"
INELIGIBLE_LABELS = frozenset({"l5:blocked", "l5:parked", "l5:owner"})


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


def _main_sha(main_ref: object) -> str:
    if _str(main_ref, "ref", "main_ref") != MAIN_REF:
        raise InvalidPayload("invalid main_ref.ref")
    target = _get(main_ref, "object", "main_ref")
    if _str(target, "type", "main_ref.object") != "commit":
        raise InvalidPayload("invalid main_ref.object.type")
    return _str(target, "sha", "main_ref.object")


def _issues(pages: object, complete: object) -> tuple[list[int], list[int], list[int]]:
    issue_ids: list[int] = []
    next_ids: list[int] = []
    ineligible: list[int] = []
    seen: set[int] = set()
    for i, raw in enumerate(_rest_items(pages, complete, "issues")):
        path = f"issues[{i}]"
        if type(raw) is not dict:
            raise InvalidPayload(f"invalid {path}")
        if "pull_request" in raw:  # the issues endpoint also lists pull requests
            continue
        number = _get(raw, "number", path)
        if type(number) is not int or number <= 0:  # a JSON boolean is never an id
            raise InvalidPayload(f"invalid {path}.number")
        if _str(raw, "state", path) != "open":
            raise InvalidPayload(f"invalid {path}.state")
        labels = _get(raw, "labels", path)
        if type(labels) is not list:
            raise InvalidPayload(f"invalid {path}.labels")
        names = {_str(label, "name", f"{path}.labels[{j}]") for j, label in enumerate(labels)}
        if number in seen:
            raise InvalidPayload("duplicate issues.number")
        seen.add(number)
        issue_ids.append(number)
        if NEXT_LABEL in names:
            next_ids.append(number)
        if names & INELIGIBLE_LABELS:
            ineligible.append(number)
    return sorted(issue_ids), sorted(next_ids), sorted(ineligible)


def _branches(pages: object, complete: object) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(_rest_items(pages, complete, "branches")):
        name = _str(raw, "name", f"branches[{i}]")
        if name in seen:
            raise InvalidPayload("duplicate branches.name")
        seen.add(name)
        names.append(name)
    return sorted(names)


def work_observation(
    main_ref: object,
    *,
    issue_pages: Sequence[object],
    issues_complete: bool,
    branch_pages: Sequence[object],
    branches_complete: bool,
) -> dict[str, Any]:
    """Return the GitHub-derived work fields, or raise InvalidPayload.

    ``observed_main_sha``, ``issue_ids``, ``next_ids`` and
    ``ineligible_issue_ids`` belong in the report's ``snapshot`` section;
    ``branches`` is its top-level ``branches`` list.
    """
    issue_ids, next_ids, ineligible = _issues(issue_pages, issues_complete)
    return {
        "observed_main_sha": _main_sha(main_ref),
        "issue_ids": issue_ids,
        "next_ids": next_ids,
        "ineligible_issue_ids": ineligible,
        "branches": _branches(branch_pages, branches_complete),
    }
