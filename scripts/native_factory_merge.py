#!/usr/bin/env python3
import json
import os
import subprocess
from pathlib import Path

repo = os.environ["GITHUB_REPOSITORY"]
owner, name = repo.split("/", 1)
required = set(json.loads(os.environ["REQUIRED_CHECKS_JSON"]))
event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())


def gh(path, method=None, fields=None):
    command = ["gh", "api"]
    if method:
        command += ["-X", method]
    if fields:
        for key, value in fields.items():
            command += ["-f", f"{key}={value}"]
    command.append(path)
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or f"GitHub API failed: {path}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


number = None
if os.environ["GITHUB_EVENT_NAME"] == "pull_request_review":
    number = event.get("pull_request", {}).get("number")
elif os.environ["GITHUB_EVENT_NAME"] == "workflow_run":
    workflow_run = event.get("workflow_run", {})
    pull_requests = workflow_run.get("pull_requests") or []
    if pull_requests:
        number = pull_requests[0].get("number")
    elif workflow_run.get("head_sha"):
        matches = gh(
            f"repos/{repo}/commits/{workflow_run['head_sha']}/pulls?per_page=20"
        )
        matches = [item for item in matches if item.get("state") == "open"]
        if len(matches) == 1:
            number = matches[0]["number"]

if not number:
    print("NO_CANONICAL_PR_FOR_EVENT")
    raise SystemExit(0)

pr = gh(f"repos/{repo}/pulls/{number}")
if pr.get("state") != "open" or pr.get("draft"):
    raise SystemExit(0)
if pr.get("base", {}).get("ref") != "main":
    print("NON_MAIN_BASE_BLOCKED")
    raise SystemExit(0)
if pr.get("head", {}).get("repo", {}).get("full_name") != repo:
    print("FOREIGN_HEAD_BLOCKED")
    raise SystemExit(0)

sha = pr["head"]["sha"]
checks = gh(f"repos/{repo}/commits/{sha}/check-runs?per_page=100").get(
    "check_runs", []
)
passing = {
    check["name"]
    for check in checks
    if check.get("status") == "completed" and check.get("conclusion") == "success"
}
missing = sorted(required - passing)
if missing:
    print("REQUIRED_CHECKS_NOT_GREEN", missing)
    raise SystemExit(0)

reviews = gh(f"repos/{repo}/pulls/{number}/reviews?per_page=100")
author = pr.get("user", {}).get("login", "").lower()
approved = [
    review
    for review in reviews
    if review.get("state") == "APPROVED"
    and review.get("commit_id") == sha
    and review.get("user", {}).get("login", "").lower() != author
]
adverse = [
    review
    for review in reviews
    if review.get("state") == "CHANGES_REQUESTED" and review.get("commit_id") == sha
]
if not approved or adverse:
    print("INDEPENDENT_EXACT_HEAD_REVIEW_NOT_CLEAN")
    raise SystemExit(0)

query = """query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviewThreads(first:100){nodes{isResolved}}
    }
  }
}"""
result = subprocess.run(
    [
        "gh",
        "api",
        "graphql",
        "-F",
        f"owner={owner}",
        "-F",
        f"name={name}",
        "-F",
        f"number={number}",
        "-f",
        f"query={query}",
    ],
    text=True,
    capture_output=True,
    check=False,
)
if result.returncode:
    raise SystemExit("REVIEW_THREAD_RECONCILIATION_UNAVAILABLE")
threads = json.loads(result.stdout)["data"]["repository"]["pullRequest"][
    "reviewThreads"
]["nodes"]
if any(not thread.get("isResolved") for thread in threads):
    print("UNRESOLVED_REVIEW_THREADS")
    raise SystemExit(0)

pr = gh(f"repos/{repo}/pulls/{number}")
if pr.get("head", {}).get("sha") != sha or pr.get("mergeable") is not True:
    print("HEAD_MOVED_OR_NOT_MERGEABLE")
    raise SystemExit(0)

merged = gh(
    f"repos/{repo}/pulls/{number}/merge",
    method="PUT",
    fields={"sha": sha, "merge_method": "squash"},
)
if not merged.get("merged"):
    raise SystemExit("MERGE_REJECTED")
print(f"NATIVE_FACTORY_MERGED PR #{number} exact head {sha}")
