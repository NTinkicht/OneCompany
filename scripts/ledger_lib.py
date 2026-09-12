"""Durable GitHub Team Room ledger helpers for distributed OneCompany runs."""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from typing import Any

from onecompany_lib import CONTROL, command_exists, github_repo_from_config, load_json, run

MARKER = "<!-- onecompany-ledger-v1 -->"
EVENT_RE = re.compile(r"<!-- onecompany-ledger-v1 -->\s*```json\s*(\{.*?\})\s*```", re.DOTALL)


def ledger_config() -> dict[str, Any]:
    return load_json(CONTROL / "ledger.json")


def ledger_enabled() -> bool:
    return bool(ledger_config().get("enabled"))


def _repo_and_issue() -> tuple[str, int]:
    config = load_json(CONTROL / "config.json")
    ledger = ledger_config()
    repo = github_repo_from_config(config)
    issue = ledger.get("issue_number")
    if not repo:
        raise RuntimeError("config.project.repository must be owner/name")
    if not isinstance(issue, int) or issue <= 0:
        raise RuntimeError("ledger.issue_number must be configured")
    return repo, issue


def _trusted_publishers() -> set[str]:
    return set(ledger_config().get("trusted_publisher_logins", []))


def _gh_json(args: list[str]) -> Any:
    if not command_exists("gh"):
        raise RuntimeError("gh CLI is required for durable ledger access")
    result = run(["gh", *args])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return json.loads(result.stdout)


def list_events() -> list[dict[str, Any]]:
    repo, issue = _repo_and_issue()
    trusted = _trusted_publishers()
    raw = _gh_json(["api", "--paginate", "--slurp", f"repos/{repo}/issues/{issue}/comments?per_page=100"])
    pages = raw if isinstance(raw, list) else [raw]
    comments: list[dict[str, Any]] = []
    for page in pages:
        if isinstance(page, list):
            comments.extend(item for item in page if isinstance(item, dict))
        elif isinstance(page, dict):
            comments.append(page)

    events: list[dict[str, Any]] = []
    for comment in comments:
        login = ((comment.get("user") or {}).get("login"))
        if trusted and login not in trusted:
            continue
        match = EVENT_RE.search(comment.get("body") or "")
        if not match:
            continue
        try:
            event = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        event["github_comment_id"] = comment.get("id")
        event["github_comment_url"] = comment.get("html_url")
        event["github_publisher"] = login
        events.append(event)
    events.sort(key=lambda item: (item.get("timestamp") or "", item.get("event_id") or ""))
    return events


def post_event(event_type: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
    ledger = ledger_config()
    if not ledger.get("enabled"):
        raise RuntimeError("durable ledger is disabled")
    if event_type not in set(ledger.get("accepted_event_types", [])):
        raise RuntimeError(f"unsupported ledger event type: {event_type}")
    trusted = _trusted_publishers()
    if not trusted:
        raise RuntimeError("ledger requires at least one trusted publisher login")
    repo, issue = _repo_and_issue()
    event = {
        "version": int(ledger.get("event_format_version", 1)),
        "event_id": str(uuid.uuid4()),
        "type": event_type,
        "actor": actor,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "payload": payload,
    }
    body = f"{MARKER}\n```json\n{json.dumps(event, separators=(',', ':'), ensure_ascii=False)}\n```\n"
    posted = _gh_json(["api", "--method", "POST", f"repos/{repo}/issues/{issue}/comments", "-f", f"body={body}"])
    login = ((posted.get("user") or {}).get("login"))
    if login not in trusted:
        comment_id = posted.get("id")
        if comment_id:
            run(["gh", "api", "--method", "DELETE", f"repos/{repo}/issues/comments/{comment_id}"])
        raise RuntimeError(f"ledger publisher {login!r} is not trusted; event rejected")
    event["github_comment_id"] = posted.get("id")
    event["github_comment_url"] = posted.get("html_url")
    event["github_publisher"] = login
    return event


def derive(events: list[dict[str, Any]], pr: int | None = None) -> dict[str, Any]:
    active: dict[str, dict[str, Any]] = {}
    authors_by_pr: dict[int, set[str]] = {}
    gates_by_pr: dict[int, dict[str, Any]] = {}

    for event in events:
        event_type = event.get("type")
        actor = event.get("actor")
        payload = event.get("payload") or {}
        event_pr = payload.get("pr")
        if isinstance(event_pr, str) and event_pr.isdigit():
            event_pr = int(event_pr)
        if isinstance(event_pr, int):
            authors_by_pr.setdefault(event_pr, set())

        if event_type == "ROLE_LEASE_ASSIGNED":
            lease_id = payload.get("lease_id")
            if lease_id:
                active[str(lease_id)] = {
                    "id": str(lease_id),
                    "role": payload.get("role", "implementation"),
                    "actor": actor,
                    "work_unit": payload.get("work_unit"),
                    "branch": payload.get("branch"),
                    "pr": event_pr,
                    "start_head": payload.get("start_head"),
                    "status": "active",
                    "event": event,
                }
            if payload.get("role", "implementation") == "implementation" and isinstance(event_pr, int) and actor:
                authors_by_pr[event_pr].add(str(actor))
        elif event_type == "ROLE_LEASE_RELEASED":
            lease_id = payload.get("lease_id")
            if lease_id:
                active.pop(str(lease_id), None)
        elif event_type == "MATERIAL_AUTHOR" and isinstance(event_pr, int) and actor:
            authors_by_pr[event_pr].add(str(actor))
        elif event_type == "GATE" and isinstance(event_pr, int):
            gates_by_pr[event_pr] = {
                "pr": event_pr,
                "sha": payload.get("sha"),
                "reviewer_actor": actor,
                "verdict": payload.get("verdict"),
                "material_authors": payload.get("material_authors", []),
                "evidence": payload.get("evidence", []),
                "summary": payload.get("summary", ""),
                "stale": False,
                "github_comment_url": event.get("github_comment_url"),
                "github_publisher": event.get("github_publisher"),
                "timestamp": event.get("timestamp"),
            }

    active_values = list(active.values())
    if pr is not None:
        active_values = [item for item in active_values if item.get("pr") == pr]
        authors = sorted(authors_by_pr.get(pr, set()))
        gate = gates_by_pr.get(pr)
    else:
        authors = sorted({author for values in authors_by_pr.values() for author in values})
        gate = None

    return {
        "active_leases": active_values,
        "material_authors": authors,
        "current_gate": gate,
        "gates_by_pr": gates_by_pr,
    }
