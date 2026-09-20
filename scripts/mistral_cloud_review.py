#!/usr/bin/env python3
"""Source-only trusted PR target validator for advisory Mistral cloud review.

Run from the protected default branch *before* checking out untrusted PR code.
The model gets read-only tools; no model output authorizes merging or writing.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = "NTinkicht/OneCompany"
WAKE_ISSUE = 130
SHA = re.compile(r"[0-9a-f]{40}\Z")
PR_NUMBER = re.compile(r"[1-9][0-9]{0,5}\Z")
FIELD = re.compile(r"(?m)^([a-z_]+):[ \t]*([^\r\n]*?)[ \t]*$")
REQUIRED_CI = frozenset({
    "OneCompany Validate",
    "OneCompany Ledger Read Smoke",
    "OneCompany Handoff Supervision",
})
MISTRAL_ALIASES = frozenset({"mistral", "mistral-vibe", "mistral_vibe"})
MATERIAL_AUTHOR = re.compile(r"(?im)^Material-Author:[ \t]*([a-z0-9_-]+)[ \t]*$")
DIFF_NAME = ".onecompany_mistral_review.diff"
MAX_DIFF_BYTES = 100_000


def parse_dispatch(body: str) -> tuple[int, str, str]:
    if len(body) > 4096 or body.count("MISTRAL_REVIEW_V1") != 1:
        raise ValueError("MISSING_OR_REPEATED_REVIEW_MARKER")
    if len(re.findall(r"(?m)^MISTRAL_REVIEW_V1[ \t]*$", body)) != 1:
        raise ValueError("UNANCHORED_REVIEW_MARKER")
    fields: dict[str, str] = {}
    for name, value in FIELD.findall(body):
        if name in fields:
            raise ValueError("DUPLICATE_REVIEW_FIELD")
        fields[name] = value.strip()
    if set(fields) != {"pr", "head_sha", "base_sha"}:
        raise ValueError("REVIEW_FIELD_SET_INVALID")
    if not PR_NUMBER.fullmatch(fields["pr"]):
        raise ValueError("REVIEW_PR_INVALID")
    if not SHA.fullmatch(fields["head_sha"]) or not SHA.fullmatch(fields["base_sha"]):
        raise ValueError("REVIEW_SHA_INVALID")
    if fields["head_sha"] == fields["base_sha"]:
        raise ValueError("REVIEW_HAS_NO_DIFF")
    return int(fields["pr"]), fields["head_sha"], fields["base_sha"]


def github_json(route: str):
    payload = subprocess.check_output(
        ["gh", "api", route], stderr=subprocess.DEVNULL, timeout=25
    )
    return json.loads(payload)


def current_pr(number: int, head: str, base: str) -> dict:
    pr = github_json(f"repos/{REPO}/pulls/{number}")
    if (
        pr.get("state") != "open"
        or pr.get("head", {}).get("sha") != head
        or pr.get("base", {}).get("sha") != base
        or pr.get("base", {}).get("ref") != "main"
        or pr.get("head", {}).get("repo", {}).get("full_name") != REPO
        or pr.get("base", {}).get("repo", {}).get("full_name") != REPO
        or pr.get("number") != number
    ):
        raise ValueError("STALE_OR_FOREIGN_REVIEW_PR")
    return pr


def independent_material_authors(number: int, expected_head: str) -> bool:
    """Fail closed for any explicit Mistral material authorship.

    Without exhaustive actor provenance, this lane can only be ADVISORY;
    GitHub OAuth author names alone cannot establish model independence.
    """
    count = 0
    last_sha = None
    for page in range(1, 6):
        commits = github_json(
            f"repos/{REPO}/pulls/{number}/commits?per_page=100&page={page}"
        )
        if not isinstance(commits, list):
            raise ValueError("COMMIT_PROVENANCE_UNAVAILABLE")
        for item in commits:
            count += 1
            last_sha = item.get("sha")
            if not SHA.fullmatch(last_sha or ""):
                raise ValueError("COMMIT_PROVENANCE_SHA_INVALID")
            message = item.get("commit", {}).get("message", "")
            tags = MATERIAL_AUTHOR.findall(message)
            if len(tags) > 1 or any(t.lower() in MISTRAL_ALIASES for t in tags):
                raise ValueError("MISTRAL_SELF_REVIEW_BLOCKED")
            account = (item.get("author") or {}).get("login", "").lower()
            if account in MISTRAL_ALIASES:
                raise ValueError("MISTRAL_SELF_REVIEW_BLOCKED")
        if len(commits) < 100:
            if last_sha != expected_head:
                raise ValueError("COMMIT_PROVENANCE_STALE")
            return count > 0
    raise ValueError("COMMIT_PROVENANCE_OVER_LIMIT")


def latest_ci_green(head: str) -> bool:
    result = github_json(
        f"repos/{REPO}/actions/runs?head_sha={head}&event=pull_request&per_page=100"
    )
    runs = result.get("workflow_runs", [])
    for name in REQUIRED_CI:
        matching = [
            r for r in runs
            if r.get("head_sha") == head
            and r.get("event") == "pull_request"
            and r.get("name") == name
        ]
        if not matching:
            return False
        last = max(
            matching,
            key=lambda r: (
                r.get("run_number") or 0,
                r.get("run_attempt") or 0,
                r.get("id") or 0,
            ),
        )
        if last.get("status") != "completed" or last.get("conclusion") != "success":
            return False
    return True


def output(**fields: object) -> None:
    path = os.environ["GITHUB_OUTPUT"]
    with open(path, "a", encoding="utf-8") as stream:
        for key, value in fields.items():
            if "\n" in str(value) or "\r" in str(value):
                raise ValueError("Unsafe Actions output")
            stream.write(f"{key}={value}\n")


def prepare() -> None:
    try:
        if os.environ["GITHUB_REPOSITORY"] != REPO:
            raise ValueError("FOREIGN_REVIEW_REPOSITORY")
        number, head, base = parse_dispatch(os.environ["DISPATCH_BODY"])
        current_pr(number, head, base)
        if not independent_material_authors(number, head):
            raise ValueError("REVIEW_HAS_NO_COMMITS")
        if not latest_ci_green(head):
            raise ValueError("REVIEW_CI_NOT_GREEN")
    except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired, KeyError):
        # No untrusted input or token is echoed to Actions outputs.
        output(ready="false", status="REVIEW_TARGET_BLOCKED")
        return
    output(ready="true", status="OK", pr=number, sha=head, base=base)


def evidence() -> None:
    try:
        number = int(os.environ["REVIEW_PR"])
        head = os.environ["REVIEW_SHA"]
        base = os.environ["REVIEW_BASE"]
        if not SHA.fullmatch(head) or not SHA.fullmatch(base):
            raise ValueError("REVIEW_SHA_INVALID")
        current_pr(number, head, base)
        if not independent_material_authors(number, head) or not latest_ci_green(head):
            raise ValueError("REVIEW_TARGET_STALE")
        actual_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, timeout=10
        ).decode("ascii").strip()
        if actual_head != head:
            raise ValueError("REVIEW_CHECKOUT_STALE")
        diff = subprocess.check_output(
            ["git", "diff", "--no-ext-diff", "--no-textconv",
             "--no-color", "--no-renames", base, head, "--"],
            stderr=subprocess.DEVNULL, timeout=20,
        )
        if not diff or len(diff) > MAX_DIFF_BYTES:
            raise ValueError("REVIEW_DIFF_BOUND_EXCEEDED")
        path = Path(DIFF_NAME)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(diff)
    except (ValueError, OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, KeyError):
        output(ready="false", status="REVIEW_EVIDENCE_BLOCKED")
        return
    output(ready="true", status="OK")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "prepare":
        prepare()
    elif mode == "evidence":
        evidence()
    else:
        raise SystemExit("usage: mistral_cloud_review.py prepare|evidence")
