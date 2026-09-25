#!/usr/bin/env python3
"""Source-only GitHub-native Grok Bot review/test inbox, never an execution lease.

A result is accepted ONLY if GitHub's issue_comment actor is the actual App bot.
Owner OAuth comments and a screenshot are not bot attestations. The GitHub-hosted
publisher reports advisory evidence; it never approves, merges or pushes code.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = "NTinkicht/OneCompany"
INBOX_ISSUE = 131
BOT_LOGIN = "onecompany-grok-worker[bot]"
MARKER = "GROK_RESULT_V1"
SHA = re.compile(r"[0-9a-f]{40}\Z")
SAFE_PATH = re.compile(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\Z")
AUTHOR_TAG = re.compile(r"(?im)^Material-Author:[ \t]*([a-z0-9_-]+)[ \t]*$")
VERDICTS = frozenset({"NO_BLOCKING_FINDINGS", "CHANGES_REQUIRED", "INSUFFICIENT_EVIDENCE"})
SEVERITIES = frozenset({"CRITICAL", "MAJOR", "MINOR", "INFO"})
ALIASES = frozenset({
    "grok", "grok-bot", "grok-4-6-interactive", "onecompany-grok-worker",
    BOT_LOGIN,
})


def github(route: str):
    return json.loads(subprocess.check_output(
        ["gh", "api", route], timeout=30, stderr=subprocess.DEVNULL
    ))


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate JSON keys at *every* depth before the final value wins."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("GROK_DUPLICATE_RESULT_KEY")
        result[key] = value
    return result


def reject_nonfinite(_value: str) -> None:
    raise ValueError("GROK_NONFINITE_RESULT_NUMBER")


def strict_result(raw: str) -> dict:
    """Untrusted Bot JSON must match exact contract; reject control-plane prose."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 12_000:
        raise ValueError("GROK_RESULT_SIZE_BLOCKED")
    if raw.count(MARKER) != 1 or not raw.startswith(MARKER + "\n"):
        raise ValueError("GROK_RESULT_MARKER_INVALID")
    # Do not let JSON duplicate-key last-wins semantics rewrite a bot verdict,
    # target SHA, finding severity or any nested provenance-bearing field.
    value = json.loads(
        raw[len(MARKER) + 1:],
        object_pairs_hook=unique_object,
        parse_constant=reject_nonfinite,
    )
    if not isinstance(value, dict) or set(value) != {
        "version", "kind", "repo", "pr", "head_sha", "base_sha",
        "execution_id", "verdict", "findings", "summary",
    }:
        raise ValueError("GROK_RESULT_FIELDS_INVALID")
    if (type(value["version"]) is not int or value["version"] != 1
        or value["kind"] not in ("review", "test")
        or value["repo"] != REPO
        or type(value["pr"]) is not int or not 1 <= value["pr"] <= 999999
        or not isinstance(value["head_sha"], str)
        or not isinstance(value["base_sha"], str)
        or not SHA.fullmatch(value["head_sha"])
        or not SHA.fullmatch(value["base_sha"])
        or value["head_sha"] == value["base_sha"]
        or not isinstance(value["execution_id"], str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", value["execution_id"])
        or not isinstance(value["verdict"], str)
        or value["verdict"] not in VERDICTS
        or not isinstance(value["summary"], str)
        or not 1 <= len(value["summary"]) <= 1800
        or not isinstance(value["findings"], list)
        or len(value["findings"]) > 12):
        raise ValueError("GROK_RESULT_INVALID")
    for item in value["findings"]:
        if (not isinstance(item, dict)
            or set(item) != {"severity", "path", "line", "description"}
            or item["severity"] not in SEVERITIES
            or not isinstance(item["path"], str)
            or not SAFE_PATH.fullmatch(item["path"])
            or any(p in {"..", ".", ".git", ".vibe"} for p in Path(item["path"]).parts)
            or type(item["line"]) is not int
            or item["line"] < 1 or item["line"] > 1_000_000
            or not isinstance(item["description"], str)
            or not 1 <= len(item["description"]) <= 1200):
            raise ValueError("GROK_FINDING_INVALID")
    if value["verdict"] == "NO_BLOCKING_FINDINGS" and any(
        item["severity"] in ("CRITICAL", "MAJOR") for item in value["findings"]
    ):
        raise ValueError("GROK_VERDICT_INCONSISTENT")
    return value


def prove_pr_and_independence(value: dict) -> dict:
    pr = github(f"repos/{REPO}/pulls/{value['pr']}")
    if not isinstance(pr, dict):
        raise ValueError("GROK_PR_UNAVAILABLE")
    head = pr.get("head")
    base = pr.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise ValueError("GROK_PR_UNAVAILABLE")
    head_repo, base_repo = head.get("repo"), base.get("repo")
    if not isinstance(head_repo, dict) or not isinstance(base_repo, dict):
        raise ValueError("GROK_PR_UNAVAILABLE")
    if (pr.get("number") != value["pr"] or pr.get("state") != "open"
        or head.get("sha") != value["head_sha"]
        or base.get("sha") != value["base_sha"]
        or base.get("ref") != "main"
        or head_repo.get("full_name") != REPO
        or base_repo.get("full_name") != REPO):
        raise ValueError("GROK_PR_STALE_OR_FOREIGN")
    count = 0
    last = None
    for page in range(1, 6):
        rows = github(f"repos/{REPO}/pulls/{value['pr']}/commits?per_page=100&page={page}")
        if not isinstance(rows, list):
            raise ValueError("GROK_AUTHORS_UNAVAILABLE")
        for item in rows:
            count += 1
            last = item.get("sha")
            if not isinstance(last, str) or not SHA.fullmatch(last):
                raise ValueError("GROK_AUTHOR_SHA_INVALID")
            logins = {
                ((item.get("author") or {}).get("login") or "").lower(),
                ((item.get("committer") or {}).get("login") or "").lower(),
            }
            if any(login in ALIASES for login in logins):
                raise ValueError("GROK_SELF_REVIEW_BLOCKED")
            message = (item.get("commit") or {}).get("message") or ""
            if any(tag.lower() in ALIASES for tag in AUTHOR_TAG.findall(message)):
                raise ValueError("GROK_SELF_REVIEW_BLOCKED")
        if len(rows) < 100:
            if count == 0 or last != value["head_sha"]:
                raise ValueError("GROK_COMMIT_PROVENANCE_STALE")
            return pr
    raise ValueError("GROK_AUTHORS_OVER_LIMIT")


def already_published(value: dict, comment_id: int) -> bool:
    """Idempotent at the actual source comment ID; no self-replay on retries."""
    for page in range(1, 7):
        rows = github(
            f"repos/{REPO}/issues/{value['pr']}/comments?per_page=100&page={page}"
        )
        if not isinstance(rows, list):
            raise ValueError("GROK_HISTORY_UNAVAILABLE")
        for item in rows:
            if (item.get("user") or {}).get("login") == "github-actions[bot]" and (
                f"source_comment_id={comment_id}" in (item.get("body") or "")
            ):
                return True
        if len(rows) < 100:
            return False
    raise ValueError("GROK_HISTORY_OVER_LIMIT")


def verify(
    raw: str, *,
    actor: str, repository: str, issue_number: int,
    source_comment_id: int,
) -> dict:
    if (actor != BOT_LOGIN or repository != REPO
        or type(issue_number) is not int or issue_number != INBOX_ISSUE
        or type(source_comment_id) is not int or source_comment_id < 1):
        raise ValueError("GROK_IDENTITY_OR_INBOX_BLOCKED")
    value = strict_result(raw)
    prove_pr_and_independence(value)
    # Never turn an absent/failed CI into a successful advisory artifact.
    import mistral_cloud_review
    if not mistral_cloud_review.latest_ci_green(value["pr"], value["head_sha"]):
        raise ValueError("GROK_CI_NOT_GREEN")
    if already_published(value, source_comment_id):
        raise ValueError("GROK_DUPLICATE_SOURCE_COMMENT")
    value["source_comment_id"] = source_comment_id
    value["source_actor"] = actor
    value["body_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return value


def comment_text(value: dict) -> str:
    lines = [
        "**Grok Bot cloud exact-head independent ADVISORY evidence (non-binding)**",
        f"source_comment_id={value['source_comment_id']}",
        f"Authenticated GitHub source: {value['source_actor']} on issue #{INBOX_ISSUE}",
        f"Native execution ID (provider-asserted, not independently inspected): {value['execution_id']}",
        f"PR #{value['pr']}, head {value['head_sha']}, base {value['base_sha']}",
        f"Kind: {value['kind']}; verdict: {value['verdict']}",
        f"Body SHA-256: {value['body_sha256']}",
        "",
        value["summary"],
        "",
    ]
    for item in value["findings"]:
        # All fields remain UNTRUSTED model data, never executed as commands.
        lines.append(
            f"- [{item['severity']}] {item['path']}:{item['line']} - {item['description']}"
        )
    lines.extend(["", "No binding gate, approval, code write or merge authority."])
    return "\n".join(lines)[:19000] + "\n"


def output(**values: object) -> None:
    path = os.environ["GITHUB_OUTPUT"]
    with open(path, "a", encoding="utf-8") as stream:
        for key, value in values.items():
            if "\n" in str(value) or "\r" in str(value):
                raise ValueError("unsafe Actions output")
            stream.write(f"{key}={value}\n")


def main() -> int:
    try:
        value = verify(
            os.environ["SOURCE_BODY"],
            actor=os.environ["SOURCE_ACTOR"],
            repository=os.environ["GITHUB_REPOSITORY"],
            issue_number=int(os.environ["SOURCE_ISSUE"]),
            source_comment_id=int(os.environ["SOURCE_COMMENT_ID"]),
        )
        output(ready="true", status="GROK_ADVISORY_VERIFIED",
               pr=value["pr"], sha=value["head_sha"], base=value["base_sha"])
        Path("/tmp/onecompany-grok-validated.json").write_text(json.dumps(value))
        Path("/tmp/onecompany-grok-public.txt").write_text(comment_text(value))
    except (ValueError, KeyError, TypeError, AttributeError, OSError,
            json.JSONDecodeError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired):
        output(ready="false", status="GROK_REVIEW_BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
