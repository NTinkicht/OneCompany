#!/usr/bin/env python3
"""Read-only verifier for TWO real, isolated A4 disposable installations.

Do not confuse this live evidence check with the synthetic self-tests.
Requires a separately generated non-secret manifest and a read-only GitHub
token. It never creates repositories, merges PRs or promotes autonomy.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from a4_pr_producer import GitHub, Refused, SHA, branch_for, fixture_body


def verify_installation(entry: dict, token: str) -> dict:
    repo = entry["repository"]
    wu = entry["work_unit"]
    actor = entry["actor"]
    head = entry["head"]
    base = entry["base"]
    number = entry["pr"]
    run_id = entry["workflow_run"]
    check_name = entry["check_name"]
    branch = branch_for(wu)
    if not all(isinstance(value, str) and value for value in
               (repo, actor, check_name)):
        raise Refused("manifest_identity_missing")
    if not SHA.fullmatch(head) or not SHA.fullmatch(base):
        raise Refused("manifest_exact_sha_missing")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise Refused("manifest_pr_invalid")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise Refused("manifest_run_invalid")
    api = GitHub(repo, token)
    meta = api.call("GET", "/")
    pr = api.call("GET", "/pulls/" + str(number))
    if (pr.get("head", {}).get("sha") != head
        or pr.get("head", {}).get("ref") != branch
        or pr.get("head", {}).get("repo", {}).get("full_name") != repo
        or pr.get("base", {}).get("sha") != base
        or pr.get("base", {}).get("ref") != meta.get("default_branch")
        or pr.get("base", {}).get("repo", {}).get("full_name") != repo):
        raise Refused("manifest_pr_not_exact_live_identity")
    original = fixture_body(repo, wu, actor, base)
    commit = api.call("GET", "/git/commits/" + head)
    if (len(commit.get("parents", [])) != 1
        or commit["parents"][0].get("sha") != base):
        raise Refused("manifest_not_initial_fixture_claim")
    content = api.call(
        "GET", "/contents/docs/onecompany-fixture/" + wu + ".md?ref=" + head
    )
    import base64
    actual = base64.b64decode(content["content"]).decode("utf-8")
    if actual != original:
        raise Refused("manifest_fixture_content_not_exact")
    run = api.call("GET", "/actions/runs/" + str(run_id))
    if (run.get("event") != "repository_dispatch"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("repository", {}).get("full_name") != repo):
        raise Refused("unattended_project_run_not_proven")
    checks = api.call("GET", "/commits/" + head + "/check-runs?per_page=100")
    rows = checks.get("check_runs", [])
    if not any(
        item.get("name") == check_name
        and item.get("head_sha") == head
        and item.get("status") == "completed"
        and item.get("conclusion") == "success"
        for item in rows
    ):
        raise Refused("exact_head_ci_not_proven")
    return {
        "repository": repo, "work_unit": wu, "pr": number, "head": head,
        "base": base, "workflow_run": run_id, "check_name": check_name,
        "result": "DISPOSABLE_A4_UNATTENDED_CREATION_CI_VERIFIED",
        "review_and_merge": "separate independent gates, not attested by A4",
    }


def verify_pair(entries: list[dict], token: str) -> dict:
    if not isinstance(entries, list) or len(entries) != 2:
        raise Refused("exactly_two_installations_required")
    if entries[0].get("repository") == entries[1].get("repository"):
        raise Refused("installations_must_be_distinct_repositories")
    outcomes = [verify_installation(entry, token) for entry in entries]
    return {"result": "TWO_REAL_ISOLATED_A4_PILOTS_VERIFIED",
            "installations": outcomes}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path,
                        help="JSON array of two non-secret disposable-pilot records")
    args = parser.parse_args()
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = verify_pair(data, os.environ.get("GH_TOKEN", ""))
    except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
        print("A4_QUALIFICATION_REFUSED: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
