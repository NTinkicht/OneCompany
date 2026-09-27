#!/usr/bin/env python3
"""Fail-closed exact-head cumulative-author review authorization check."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from platform_identity import (
    pull_request_material_author_actor_ids,
    require_authority,
    review_platform_identity,
)


def gh_json(path: str):
    result = subprocess.run(
        ["gh", "api", path],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"GitHub API failed: {path}")
    return json.loads(result.stdout)


def reviews(repo: str, pr: int) -> list[dict]:
    values: list[dict] = []
    for page in range(1, 11):
        batch = gh_json(f"repos/{repo}/pulls/{pr}/reviews?per_page=100&page={page}")
        if not isinstance(batch, list):
            raise RuntimeError("review response is not a list")
        values.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            return values
    raise RuntimeError("review pagination bound exceeded")


def latest_decisions(values: list[dict]) -> list[dict]:
    latest: dict[str, tuple[tuple[str, int], dict]] = {}
    for review in values:
        login = ((review.get("user") or {}).get("login") or "").lower()
        state = str(review.get("state") or "").upper()
        if not login or state not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            continue
        key = (str(review.get("submitted_at") or ""), int(review.get("id") or 0))
        previous = latest.get(login)
        if previous is None or key > previous[0]:
            latest[login] = (key, review)
    return [item[1] for item in latest.values()]


def authorize(repo: str, pr: int, head: str, base: str) -> tuple[bool, list[str]]:
    authors, author_errors = pull_request_material_author_actor_ids(
        repo, pr, head, base
    )
    if authors is None:
        return False, author_errors or ["material authorship unavailable"]

    approved = False
    reasons: list[str] = []
    for review in latest_decisions(reviews(repo, pr)):
        review_id = review.get("id")
        if not isinstance(review_id, int) or review_id <= 0:
            continue
        identity, errors = review_platform_identity(
            repo,
            pr,
            review_id,
            head,
            base,
            allowed_states={"APPROVED", "CHANGES_REQUESTED"},
        )
        if identity is None:
            # Untrusted/unmapped review comments do not gain gate authority.
            continue
        ok, authority_errors = require_authority(
            identity, "code_review", authors
        )
        if not ok:
            # A material author cannot approve OR block their own work.
            continue
        state = str(review.get("state") or "").upper()
        if state == "CHANGES_REQUESTED":
            reasons.append(
                f"trusted non-author reviewer {identity.get('actor_id')} requested changes"
            )
        elif state == "APPROVED" and not errors and not authority_errors:
            approved = True

    if reasons:
        return False, reasons
    if not approved:
        return False, ["no trusted exact-head non-author approval"]
    return True, []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    ok, reasons = authorize(args.repo, args.pr, args.head, args.base)
    print(json.dumps({"ok": ok, "reasons": reasons}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
