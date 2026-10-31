"""Fail-closed derivation of a PR head's material authors from its commits (#373).

OC-P0-01 / OC-P0-05: ``PullRequestObservation.material_authors`` is the only
evidence ``live_work_reconciliation._trusted_approver`` has that an approver
did not write the head it approved. This module derives that tuple from the
exact commit list a trusted caller fetched (``GET /pulls/{n}/commits``,
oldest first) instead of trusting a pre-assembled claim.

The material authors are every commit's author login and committer login
plus every ``Material-Author:`` trailer value. Any ambiguity withholds the
whole result (``authors == ()``), which ``_trusted_approver`` already treats
as "independence not proven": a missing login, an empty trailer, a list that
does not end at the exact head, or a list GitHub may have truncated.

Read-only and pure: nothing here fetches, approves or merges.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SHA = re.compile(r"[0-9a-f]{40}")
_TRAILER = re.compile(r"^material-author:(.*)$", re.IGNORECASE | re.MULTILINE)
# GET /repos/{o}/{r}/pulls/{n}/commits returns at most 250 commits; a list
# of that length may be missing the rest, so it is never complete evidence.
COMMIT_LIST_CAP = 250


@dataclass(frozen=True)
class CommitObservation:
    """One PR commit as fetched by the trusted caller.

    ``author_login`` / ``committer_login`` are the GitHub accounts linked to
    the commit (``null`` when GitHub cannot link the email).
    """
    sha: str
    author_login: str | None
    committer_login: str | None
    message: str


@dataclass(frozen=True)
class MaterialAuthorship:
    authors: tuple[str, ...]
    findings: tuple[tuple[str, str], ...]


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _login(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _well_formed(commit: object) -> bool:
    if not isinstance(commit, CommitObservation):
        return False
    return (_valid_sha(commit.sha) and isinstance(commit.message, str)
            and all(v is None or isinstance(v, str)
                    for v in (commit.author_login, commit.committer_login)))


def derive_material_authors(
    commits: tuple[CommitObservation, ...], head_sha: str,
) -> MaterialAuthorship:
    """Return the sorted material authors of ``head_sha`` with sorted findings.

    Findings are ``(commit sha or "", CODE)``. Any finding withholds the
    authors entirely, so a partial list is never mistaken for proof that a
    reviewer is independent.
    """
    findings: set[tuple[str, str]] = set()
    if not _valid_sha(head_sha):
        findings.add(("", "INVALID_SHA"))
    if not isinstance(commits, tuple):
        findings.add(("", "INVALID_COMMIT"))
        commits = ()
    if not commits:
        findings.add(("", "NO_COMMITS"))
    if len(commits) >= COMMIT_LIST_CAP:
        findings.add(("", "COMMIT_LIST_TRUNCATED"))

    authors: set[str] = set()
    seen: set[str] = set()
    for commit in commits:
        if not _well_formed(commit):
            ref = commit.sha if isinstance(commit, CommitObservation) and _valid_sha(commit.sha) else ""
            findings.add((ref, "INVALID_COMMIT"))
            continue
        if commit.sha in seen:
            findings.add((commit.sha, "DUPLICATE_COMMIT"))
            continue
        seen.add(commit.sha)
        for login in (commit.author_login, commit.committer_login):
            if _login(login):
                authors.add(login)
            else:
                # An unlinked or blank identity could be anyone, including
                # the reviewer: never independence evidence.
                findings.add((commit.sha, "UNATTRIBUTED_COMMIT"))
        for value in _TRAILER.findall(commit.message):
            name = value.strip()
            if name:
                authors.add(name)
            else:
                findings.add((commit.sha, "INVALID_MATERIAL_AUTHOR_TRAILER"))

    last = commits[-1] if commits else None
    if commits and not (isinstance(last, CommitObservation) and last.sha == head_sha):
        findings.add(("", "HEAD_NOT_LAST_COMMIT"))

    if findings:
        return MaterialAuthorship((), tuple(sorted(findings)))
    return MaterialAuthorship(tuple(sorted(authors)), ())
