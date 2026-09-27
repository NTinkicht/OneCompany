#!/usr/bin/env python3
"""Bounded autonomous dispatcher for OneCompany external Mistral review failover."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

HOST_REPO = "NTinkicht/OneCompany"
HOST_ISSUE = 130
TARGETS = ("NTinkicht/Tabibi", "NTinkicht/veritas-atlas")
MAX_OPEN_PRS_PER_REPO = 12
MAX_DISPATCHES_PER_RUN = 6
PENDING_TTL_SECONDS = 45 * 60
AUTO_MARKER = "ONECOMPANY_L4_AUTO_DISPATCH_V1"
EVIDENCE_MARKER = "ONECOMPANY_EXTERNAL_MISTRAL_REVIEW_V1"
MATERIAL_AUTHOR = re.compile(r"(?im)^Material-Author:[ \t]*([a-z0-9_-]+)[ \t]*$")
MISTRAL = re.compile(r"(?i)(?:^|[^a-z0-9])mistral(?:[-_ ]?vibe)?(?:[^a-z0-9]|$)")
DISPATCH = re.compile(
    r"(?ms)^MISTRAL_EXTERNAL_REVIEW_V1[ \t]*$.*?"
    r"^repo:[ \t]*(?P<repo>NTinkicht/[A-Za-z0-9_.-]+)[ \t]*$.*?"
    r"^pr:[ \t]*(?P<pr>[1-9][0-9]{0,5})[ \t]*$.*?"
    r"^head_sha:[ \t]*(?P<head>[0-9a-f]{40})[ \t]*$.*?"
    r"^base_sha:[ \t]*(?P<base>[0-9a-f]{40})[ \t]*$"
)
EVIDENCE = re.compile(
    r"ONECOMPANY_EXTERNAL_MISTRAL_REVIEW_V1 "
    r"repo=(?P<repo>NTinkicht/[A-Za-z0-9_.-]+) pr=(?P<pr>[1-9][0-9]{0,5}) "
    r"head=(?P<head>[0-9a-f]{40}) base=(?P<base>[0-9a-f]{40}) "
)


def request_json(route: str, *, method: str = "GET", body: dict | None = None):
    token = os.environ.get("GH_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "onecompany-l4-external-review-dispatch",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"https://api.github.com/{route.lstrip('/')}",
        data=payload,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def normalize_actor(value: object) -> str:
    text = str(value or "").strip().lower().replace("[bot]", "")
    text = text.split("@", 1)[0]
    return re.sub(r"[^a-z0-9_-]+", "-", text).strip("-")


def same_repo_open_prs(repo: str) -> list[dict]:
    pulls = request_json(
        f"repos/{repo}/pulls?state=open&base=main&sort=updated&direction=desc"
        f"&per_page={MAX_OPEN_PRS_PER_REPO}"
    )
    if not isinstance(pulls, list):
        raise ValueError("TARGET_PULLS_UNAVAILABLE")
    result = []
    for pr in pulls:
        if (
            isinstance(pr, dict)
            and pr.get("state") == "open"
            and not pr.get("draft")
            and (pr.get("base") or {}).get("ref") == "main"
            and (pr.get("base") or {}).get("repo", {}).get("full_name") == repo
            and (pr.get("head") or {}).get("repo", {}).get("full_name") == repo
        ):
            result.append(pr)
    return result


def material_authors(repo: str, number: int, head: str) -> tuple[str, ...]:
    commits = request_json(f"repos/{repo}/pulls/{number}/commits?per_page=100")
    if not isinstance(commits, list) or not commits or len(commits) > 100:
        raise ValueError("TARGET_COMMITS_UNAVAILABLE")
    if commits[-1].get("sha") != head:
        raise ValueError("TARGET_HEAD_MOVED")
    actors: set[str] = set()
    for item in commits:
        meta = item.get("commit") or {}
        raw_author = meta.get("author") or {}
        raw_committer = meta.get("committer") or {}
        identities = (
            (item.get("author") or {}).get("login"),
            (item.get("committer") or {}).get("login"),
            raw_author.get("name"),
            raw_author.get("email"),
            raw_committer.get("name"),
            raw_committer.get("email"),
        )
        if any(MISTRAL.search(str(value or "")) for value in identities):
            raise ValueError("MISTRAL_SELF_REVIEW_BLOCKED")
        tags = MATERIAL_AUTHOR.findall(meta.get("message") or "")
        if len(tags) > 1:
            raise ValueError("MATERIAL_AUTHOR_AMBIGUOUS")
        if tags:
            actors.add(tags[0].lower())
        else:
            login = normalize_actor((item.get("author") or {}).get("login"))
            actors.add(f"github-{login}" if login else "unknown")
    actors.discard("")
    if not actors or any(MISTRAL.search(actor) for actor in actors):
        raise ValueError("MATERIAL_AUTHORS_INVALID")
    return tuple(sorted(actors))


def recent_bus_comments() -> list[dict]:
    comments: list[dict] = []
    for page in range(1, 11):
        batch = request_json(
            f"repos/{HOST_REPO}/issues/{HOST_ISSUE}/comments?per_page=100&page={page}"
        )
        if not isinstance(batch, list):
            raise ValueError("WAKE_BUS_UNAVAILABLE")
        comments.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
    return comments


def terminal_or_pending(
    comments: list[dict], *, repo: str, number: int, head: str, base: str, now: int
) -> bool:
    for item in reversed(comments):
        login = ((item.get("user") or {}).get("login") or "").lower()
        if login not in {"github-actions[bot]", "ntinkicht"}:
            continue
        body = str(item.get("body") or "")
        evidence = EVIDENCE.search(body)
        if evidence and (
            evidence.group("repo") == repo
            and int(evidence.group("pr")) == number
            and evidence.group("head") == head
            and evidence.group("base") == base
        ):
            return True
        dispatch = DISPATCH.search(body)
        if not dispatch or AUTO_MARKER not in body:
            continue
        if not (
            dispatch.group("repo") == repo
            and int(dispatch.group("pr")) == number
            and dispatch.group("head") == head
            and dispatch.group("base") == base
        ):
            continue
        created = item.get("created_at")
        if not isinstance(created, str):
            continue
        try:
            epoch = int(time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ")))
        except ValueError:
            continue
        if now - epoch < PENDING_TTL_SECONDS:
            return True
    return False


def dispatch_body(repo: str, number: int, head: str, base: str, authors: tuple[str, ...]) -> str:
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not run_id.isdigit():
        raise ValueError("DISPATCH_RUN_ID_INVALID")
    return (
        "@mistral-vibe\n"
        "MISTRAL_EXTERNAL_REVIEW_V1\n"
        f"repo: {repo}\n"
        f"pr: {number}\n"
        f"head_sha: {head}\n"
        f"base_sha: {base}\n"
        f"material_authors: {','.join(authors)}\n"
        f"<!-- {AUTO_MARKER} run={run_id} -->\n"
    )


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != HOST_REPO:
        raise SystemExit("WRONG_HOST_REPOSITORY")
    comments = recent_bus_comments()
    now = int(time.time())
    dispatched = 0
    for repo in TARGETS:
        for pr in same_repo_open_prs(repo):
            if dispatched >= MAX_DISPATCHES_PER_RUN:
                print("DISPATCH_BOUND_REACHED")
                return 0
            number = int(pr["number"])
            head = (pr.get("head") or {}).get("sha") or ""
            base = (pr.get("base") or {}).get("sha") or ""
            if not re.fullmatch(r"[0-9a-f]{40}", head) or not re.fullmatch(r"[0-9a-f]{40}", base):
                continue
            if terminal_or_pending(
                comments, repo=repo, number=number, head=head, base=base, now=now
            ):
                continue
            try:
                authors = material_authors(repo, number, head)
                body = dispatch_body(repo, number, head, base, authors)
                posted = request_json(
                    f"repos/{HOST_REPO}/issues/{HOST_ISSUE}/comments",
                    method="POST",
                    body={"body": body},
                )
                if (
                    not isinstance(posted, dict)
                    or int(posted.get("id") or 0) < 1
                    or ((posted.get("user") or {}).get("login") or "").lower()
                    != "github-actions[bot]"
                    or posted.get("body") != body
                ):
                    raise ValueError("DISPATCH_PUBLICATION_NOT_VERIFIED")
                comments.append(posted)
                dispatched += 1
                print(f"AUTO_DISPATCHED repo={repo} pr={number} head={head} base={base}")
            except (ValueError, urllib.error.URLError, TimeoutError) as exc:
                print(f"AUTO_DISPATCH_BLOCKED repo={repo} pr={number} reason={type(exc).__name__}")
    print(f"AUTO_DISPATCH_COUNT={dispatched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
