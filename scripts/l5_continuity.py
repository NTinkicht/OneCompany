#!/usr/bin/env python3
"""Deterministic L5 continuity planning for the reviewed PLAN_ONLY phase."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

POLICY_PATH = Path(".onecompany/l5.json")
MAX_PAGES = 10
ISSUE_REF = re.compile(r"(?<![A-Za-z0-9])#([1-9][0-9]{0,5})")


def gh(path: str):
    result = subprocess.run(["gh", "api", path], text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"GitHub API failed: {path}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def paged(repo: str, path: str):
    items = []
    for page in range(1, MAX_PAGES + 1):
        sep = "&" if "?" in path else "?"
        batch = gh(f"repos/{repo}/{path}{sep}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise RuntimeError("PAGINATED_RESPONSE_INVALID")
        items.extend(batch)
        if len(batch) < 100:
            return items
    raise RuntimeError("PAGINATION_BOUND_EXCEEDED")


def label_names(item: dict) -> set[str]:
    result = set()
    for label in item.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str):
            result.add(name.lower())
    return result


def active_internal_pr_rows(
    repo: str, base: str, pulls: list[dict], *, count_drafts: bool
) -> list[dict]:
    result = []
    for pr in pulls:
        head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
        if (
            (pr.get("base") or {}).get("ref") == base
            and head_repo == repo
            and (count_drafts or pr.get("draft") is not True)
            and isinstance(pr.get("number"), int)
        ):
            result.append(pr)
    return sorted(result, key=lambda row: row["number"])


def active_internal_prs(
    repo: str, base: str, pulls: list[dict], *, count_drafts: bool
) -> list[int]:
    return [
        row["number"]
        for row in active_internal_pr_rows(
            repo, base, pulls, count_drafts=count_drafts
        )
    ]


def represented_issue_numbers(pulls: list[dict]) -> set[int]:
    represented: set[int] = set()
    for pr in pulls:
        text = f"{pr.get('title') or ''}\n{pr.get('body') or ''}"
        represented.update(int(value) for value in ISSUE_REF.findall(text))
    return represented


def eligible_issues(
    issues: list[dict], ready: set[str], blocked: set[str], represented: set[int]
) -> list[dict]:
    candidates = []
    for issue in issues:
        number = issue.get("number")
        if (
            issue.get("pull_request") is not None
            or issue.get("state") != "open"
            or not isinstance(number, int)
            or number in represented
        ):
            continue
        labels = label_names(issue)
        if not labels.intersection(ready) or labels.intersection(blocked):
            continue
        candidates.append(issue)
    return sorted(candidates, key=lambda row: row["number"])


def repo_plan(repo_cfg: dict, policy: dict) -> dict:
    repo = str(repo_cfg["repository"])
    base = str(repo_cfg.get("base_branch") or "main")
    target = int(repo_cfg["target_open_prs"])
    count_drafts = repo_cfg.get("count_drafts") is True
    pull_rows = active_internal_pr_rows(
        repo,
        base,
        paged(repo, "pulls?state=open"),
        count_drafts=count_drafts,
    )
    pulls = [row["number"] for row in pull_rows]
    deficit = max(0, target - len(pulls))
    issues = eligible_issues(
        paged(repo, "issues?state=open"),
        {x.lower() for x in policy.get("ready_labels", [])},
        {x.lower() for x in policy.get("blocking_labels", [])},
        represented_issue_numbers(pull_rows),
    )
    # L4.1 never claims pairwise conflict-safety. It may nominate one next WU;
    # additional capacity remains visibly unfilled until L4.5 proves conflicts.
    selected = issues[:1] if deficit else []
    unfilled = max(0, deficit - len(selected))
    if deficit == 0:
        status = "QUOTA_SATISFIED"
    elif selected:
        status = "REPLENISHMENT_PLANNED_CONFLICT_CHECK_REQUIRED_FOR_MORE"
    else:
        status = "IDLE_CAPACITY_NO_READY_WORK"
    return {
        "repository": repo,
        "target_open_prs": target,
        "active_prs": pulls,
        "deficit": deficit,
        "selected_ready_issues": [
            {"number": row["number"], "title": row.get("title")} for row in selected
        ],
        "unfilled_slots": unfilled,
        "status": status,
    }


def plan(policy: dict) -> dict:
    if policy.get("mutation_mode") != "PLAN_ONLY":
        raise RuntimeError("UNREVIEWED_MUTATION_MODE")
    repos = policy.get("repositories")
    if not isinstance(repos, list) or not repos:
        raise RuntimeError("L5_REPOSITORIES_INVALID")
    rows = [repo_plan(cfg, policy) for cfg in repos]
    return {
        "level": policy.get("level"),
        "phase": policy.get("phase"),
        "mutation_mode": policy.get("mutation_mode"),
        "repositories": rows,
        "total_target_prs": sum(row["target_open_prs"] for row in rows),
        "total_active_prs": sum(len(row["active_prs"]) for row in rows),
        "total_deficit": sum(row["deficit"] for row in rows),
        "all_quotas_satisfied": all(row["deficit"] == 0 for row in rows),
    }


def selftest() -> None:
    pulls = [
        {
            "number": 5,
            "draft": False,
            "base": {"ref": "main"},
            "head": {"repo": {"full_name": "NTinkicht/OneCompany"}},
            "body": "Implements #4",
        },
        {
            "number": 6,
            "draft": True,
            "base": {"ref": "main"},
            "head": {"repo": {"full_name": "NTinkicht/OneCompany"}},
        },
    ]
    assert active_internal_prs(
        "NTinkicht/OneCompany", "main", pulls, count_drafts=True
    ) == [5, 6]
    assert active_internal_prs(
        "NTinkicht/OneCompany", "main", pulls, count_drafts=False
    ) == [5]
    assert represented_issue_numbers(pulls) == {4}
    issues = [
        {"number": 4, "state": "open", "labels": [{"name": "l4-ready"}]},
        {"number": 7, "state": "open", "labels": [{"name": "l4-ready"}]},
        {
            "number": 2,
            "state": "open",
            "labels": [{"name": "l4-ready"}, {"name": "human-only"}],
        },
    ]
    assert [
        row["number"]
        for row in eligible_issues(issues, {"l4-ready"}, {"human-only"}, {4})
    ] == [7]
    print("l5_continuity selftest PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if os.environ.get("GITHUB_REPOSITORY") != "NTinkicht/OneCompany":
        raise SystemExit("L5_BLOCKED: wrong control-plane repository")
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    print(json.dumps(plan(policy), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
