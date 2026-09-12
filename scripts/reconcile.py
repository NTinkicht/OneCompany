#!/usr/bin/env python3
"""Reconcile the cached OneCompany state with live GitHub using the GitHub CLI.

Read-only by default. Pass --write to update .onecompany/state.json after inspection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from onecompany_lib import CONTROL, active_implementation_leases, command_exists, github_repo_from_config, load_json, run, save_json


def gh_json(args: list[str]):
    result = run(["gh", *args])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Update state.json; otherwise print proposed reconciliation")
    args = parser.parse_args()

    if not command_exists("gh"):
        print("ERROR: gh CLI is required for live GitHub reconciliation")
        return 2

    config = load_json(CONTROL / "config.json")
    state = load_json(CONTROL / "state.json")
    queue = load_json(CONTROL / "queue.json")
    repo = github_repo_from_config(config)
    if not repo:
        print("ERROR: config.project.repository must be owner/name")
        return 2
    default_branch = config.get("project", {}).get("default_branch", "main")

    try:
        commit = gh_json(["api", f"repos/{repo}/commits/{default_branch}"])
        prs = gh_json(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "number,title,headRefName,headRefOid,isDraft"])
    except Exception as exc:
        print(f"ERROR: cannot reconcile GitHub state: {exc}")
        return 2

    proposed = dict(state)
    proposed["generated_or_reconciled_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    proposed["repository_head"] = commit.get("sha")

    current_pr = state.get("current_pr")
    current = next((pr for pr in prs if pr.get("number") == current_pr), None) if current_pr else None
    if current:
        proposed["current_pr_head"] = current.get("headRefOid")
    elif current_pr is not None:
        proposed["current_pr"] = None
        proposed["current_pr_head"] = None
        proposed["current_gate"] = None

    proposed["ready_work_count"] = sum(1 for wu in queue.get("work_units", []) if wu.get("status") == "READY")
    active = active_implementation_leases(proposed)

    gate = proposed.get("current_gate")
    if gate and proposed.get("current_pr_head") and gate.get("sha") != proposed.get("current_pr_head"):
        gate = dict(gate)
        gate["stale"] = True
        proposed["current_gate"] = gate

    if current:
        proposed["company_state"] = "ACTIVE_IMPLEMENTATION" if active else "WAITING_OR_UNLEASED_PR"
    elif proposed["ready_work_count"] > 0:
        proposed["company_state"] = "ACTIVE_IMPLEMENTATION" if active else "FAULT_IDLE_WITH_READY_WORK"
    else:
        proposed["company_state"] = "IDLE_NO_READY_WORK"

    print(json.dumps(proposed, indent=2))
    if args.write:
        save_json(CONTROL / "state.json", proposed)
        print("Reconciled state written to .onecompany/state.json")
    else:
        print("Read-only reconciliation. Re-run with --write only after reviewing the proposed state.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
