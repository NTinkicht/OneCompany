#!/usr/bin/env python3
"""Bounded autonomous dispatcher for OneCompany external Mistral review failover."""
from __future__ import annotations

import base64
import calendar
import json
import os
import re
import time
import urllib.error
import urllib.request

import mistral_external_review as review_service

HOST_REPO = "NTinkicht/OneCompany"
HOST_ISSUE = 130
TARGETS = ("NTinkicht/Tabibi", "NTinkicht/veritas-atlas")
MAX_PR_PAGES = 5
MAX_REVIEW_ATTEMPTS_PER_TARGET = 3
MAX_DISPATCHES_PER_RUN = 6
MAX_WAKE_PAGES = 100
PENDING_TTL_SECONDS = 45 * 60
AUTO_MARKER = "ONECOMPANY_L4_AUTO_DISPATCH_V1"
EVIDENCE_MARKER = "ONECOMPANY_EXTERNAL_MISTRAL_REVIEW_V1"
HANDOFF_MARKER = "ONECOMPANY_L4_REVIEW_HANDOFF_V1"
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
HANDOFF = re.compile(
    r"ONECOMPANY_L4_REVIEW_HANDOFF_V1 "
    r"source=(?P<source>[1-9][0-9]{0,19}) "
    r"repo=(?P<repo>NTinkicht/[A-Za-z0-9_.-]+) pr=(?P<pr>[1-9][0-9]{0,5}) "
    r"head=(?P<head>[0-9a-f]{40}) base=(?P<base>[0-9a-f]{40})"
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
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}


def normalize_actor(value: object) -> str:
    text = str(value or "").strip().lower().replace("[bot]", "")
    text = text.split("@", 1)[0]
    return re.sub(r"[^a-z0-9_-]+", "-", text).strip("-")


def same_repo_open_prs(repo: str) -> list[dict]:
    result = []
    pulls = []
    for page in range(1, MAX_PR_PAGES + 1):
        batch = request_json(
            f"repos/{repo}/pulls?state=open&base=main&sort=updated&direction=asc"
            f"&per_page=100&page={page}"
        )
        if not isinstance(batch, list):
            raise ValueError("TARGET_PULLS_UNAVAILABLE")
        pulls.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError("TARGET_PULLS_OVER_LIMIT")
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
    commits: list[dict] = []
    for page in range(1, 6):
        batch = request_json(
            f"repos/{repo}/pulls/{number}/commits?per_page=100&page={page}"
        )
        if not isinstance(batch, list):
            raise ValueError("TARGET_COMMITS_UNAVAILABLE")
        commits.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
    else:
        raise ValueError("TARGET_COMMITS_OVER_LIMIT")
    if not commits or commits[-1].get("sha") != head:
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
        if len(tags) != 1:
            raise ValueError("MATERIAL_AUTHOR_PROVENANCE_INCOMPLETE")
        actors.add(tags[0].lower())
    actors.discard("")
    if not actors or any(MISTRAL.search(actor) for actor in actors):
        raise ValueError("MATERIAL_AUTHORS_INVALID")
    return tuple(sorted(actors))


def recent_bus_comments() -> list[dict]:
    """Read the complete bounded wake bus or fail closed before dispatch."""
    comments: list[dict] = []
    for page in range(1, MAX_WAKE_PAGES + 1):
        batch = request_json(
            f"repos/{HOST_REPO}/issues/{HOST_ISSUE}/comments?per_page=100&page={page}"
        )
        if not isinstance(batch, list):
            raise ValueError("WAKE_BUS_UNAVAILABLE")
        comments.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            return comments
    raise ValueError("WAKE_BUS_HISTORY_OVER_LIMIT")


def repository_dispatch_run_exists(source_comment_id: int) -> bool:
    if source_comment_id < 1:
        return False
    expected = f"External Mistral review dispatch {source_comment_id}"
    for page in range(1, 6):
        payload = request_json(
            f"repos/{HOST_REPO}/actions/workflows/"
            "onecompany-mistral-external-review.yml/runs"
            f"?event=repository_dispatch&per_page=100&page={page}"
        )
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(runs, list):
            raise ValueError("DISPATCH_RUN_RECONCILIATION_UNAVAILABLE")
        for run in runs:
            if (
                isinstance(run, dict)
                and run.get("event") == "repository_dispatch"
                and run.get("path") == ".github/workflows/onecompany-mistral-external-review.yml"
                and run.get("display_title") == expected
            ):
                return True
        if len(runs) < 100:
            return False
    raise ValueError("DISPATCH_RUN_RECONCILIATION_OVER_LIMIT")


def terminal_or_pending(
    comments: list[dict], *, repo: str, number: int, head: str, base: str,
    authors: tuple[str, ...], now: int
) -> bool:
    confirmed_sources: set[int] = set()
    for item in comments:
        if ((item.get("user") or {}).get("login") or "").lower() != "github-actions[bot]":
            continue
        handoff = HANDOFF.search(str(item.get("body") or ""))
        if handoff and (
            handoff.group("repo") == repo
            and int(handoff.group("pr")) == number
            and handoff.group("head") == head
            and handoff.group("base") == base
        ):
            confirmed_sources.add(int(handoff.group("source")))

    attempts = 0
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
            and review_service._trusted_evidence_comment(
                item, repo=repo, number=number, head=head, base=base,
                authors=authors,
            )
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
        source_id = int(item.get("id") or 0)
        if (
            source_id not in confirmed_sources
            and not repository_dispatch_run_exists(source_id)
        ):
            continue
        attempts += 1
        if attempts >= MAX_REVIEW_ATTEMPTS_PER_TARGET:
            return True
        created = item.get("created_at")
        if not isinstance(created, str):
            continue
        try:
            epoch = int(calendar.timegm(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ")))
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


def emergency_stop_active() -> bool:
    config = live_main_json(".onecompany/config.json")
    safety = config.get("safety")
    if not isinstance(safety, dict) or type(safety.get("emergency_stop")) is not bool:
        raise ValueError("EMERGENCY_STOP_STATE_INVALID")
    return safety["emergency_stop"]


def live_main_json(path: str) -> dict:
    payload = request_json(f"repos/{HOST_REPO}/contents/{path}?ref=main")
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        raise ValueError("LIVE_CONTROL_FILE_UNAVAILABLE")
    raw = base64.b64decode(str(payload.get("content") or ""), validate=False)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("LIVE_CONTROL_FILE_INVALID")
    return value


def review_capability_approved() -> bool:
    actors = live_main_json(".onecompany/actors.json")
    readiness = live_main_json(".onecompany/readiness.json")
    dispatch = live_main_json(".onecompany/dispatch.json")
    budget = live_main_json(".onecompany/budget.json")
    actor = next((x for x in actors.get("actors", []) if x.get("id") == "mistral-vibe"), {})
    ready = next((x for x in readiness.get("actors", []) if x.get("actor_id") == "mistral-vibe"), {})
    route = next((x for x in dispatch.get("actors", []) if x.get("actor_id") == "mistral-vibe"), {})
    mech = next((x for x in route.get("mechanisms", []) if x.get("id") == "vibe-exact-head-review"), {})
    ai = budget.get("ai", {})
    allowed_cost_classes = set(budget.get("cost_classes", {}).get("allowed", []))
    actor_cost_allowed = actor.get("cost_class") in allowed_cost_classes
    zero_spend = (
        ai.get("additional_monthly_spend_cap") == 0
        and all(
            ai.get(key) is False
            for key in (
                "allow_paid_fallback", "allow_overage",
                "allow_auto_topup", "allow_new_paid_vendor",
            )
        )
    )
    return (
        actor.get("enabled") is True
        and actor.get("configured") is True
        and actor_cost_allowed
        and ready.get("setup_state") == "ready"
        and ready.get("unattended", {}).get("configured") is True
        and ready.get("unattended", {}).get("verified") is True
        and "code_review" not in ready.get("temporarily_unavailable_capabilities", [])
        and "code_review" in actor.get("capabilities", [])
        and "code_review" in ready.get("verified_capabilities", [])
        and ready.get("repository_access", {}).get("review") is True
        and mech.get("configured") is True
        and mech.get("unattended") is True
        and "code_review" in mech.get("capabilities", [])
        and zero_spend
    )


def dispatch_review_workflow(
    *, body: str, source_comment_id: int
) -> None:
    if source_comment_id < 1:
        raise ValueError("DISPATCH_IDENTITY_INVALID")
    request_json(
        f"repos/{HOST_REPO}/dispatches",
        method="POST",
        body={
            "event_type": "onecompany_mistral_external_review",
            "client_payload": {
                "dispatch_body": body,
                "source_comment_id": str(source_comment_id),
            },
        },
    )


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != HOST_REPO:
        raise SystemExit("WRONG_HOST_REPOSITORY")
    if emergency_stop_active():
        print("AUTO_DISPATCH_EMERGENCY_STOP_ACTIVE")
        return 0
    if not review_capability_approved():
        print("AUTO_DISPATCH_REVIEW_CAPABILITY_NOT_APPROVED")
        return 0
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
            try:
                authors = material_authors(repo, number, head)
            except (ValueError, urllib.error.URLError, TimeoutError) as exc:
                print(f"AUTO_DISPATCH_BLOCKED repo={repo} pr={number} reason={type(exc).__name__}")
                continue
            if terminal_or_pending(
                comments, repo=repo, number=number, head=head, base=base,
                authors=authors, now=now
            ):
                continue
            try:
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
                dispatch_review_workflow(
                    body=body,
                    source_comment_id=int(posted["id"]),
                )
                receipt_body = (
                    f"<!-- {HANDOFF_MARKER} source={int(posted['id'])} "
                    f"repo={repo} pr={number} head={head} base={base} -->"
                )
                receipt = request_json(
                    f"repos/{HOST_REPO}/issues/{HOST_ISSUE}/comments",
                    method="POST",
                    body={"body": receipt_body},
                )
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("body") != receipt_body
                    or ((receipt.get("user") or {}).get("login") or "").lower()
                    != "github-actions[bot]"
                ):
                    raise ValueError("DISPATCH_HANDOFF_CONFIRMATION_FAILED")
                comments.extend([posted, receipt])
                dispatched += 1
                print(f"AUTO_DISPATCHED repo={repo} pr={number} head={head} base={base}")
            except (ValueError, urllib.error.URLError, TimeoutError) as exc:
                print(f"AUTO_DISPATCH_BLOCKED repo={repo} pr={number} reason={type(exc).__name__}")
    print(f"AUTO_DISPATCH_COUNT={dispatched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
