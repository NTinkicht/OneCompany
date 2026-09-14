#!/usr/bin/env python3
"""Reconcile cached OneCompany state with live GitHub and durable authority."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import lease_lifecycle as lifecycle
from ledger_lib import ledger_enabled, list_events
from onecompany_lib import (
    CONTROL,
    command_exists,
    github_repo_from_config,
    github_repo_from_remote,
    load_json,
    run,
    save_json,
)
from planning_lib import select_parallel_set


def gh_json(args: list[str]):
    result = run(["gh", *args])
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or "gh command failed"
        )
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if not command_exists("gh"):
        print("ERROR: gh CLI is required")
        return 2

    config = load_json(CONTROL / "config.json")
    state = load_json(CONTROL / "state.json")
    queue = load_json(CONTROL / "queue.json")
    planning = load_json(CONTROL / "planning.json")
    configured_repo = github_repo_from_config(config)
    repo = github_repo_from_remote()
    if not repo:
        print("ERROR: cannot derive repository identity from git origin")
        return 2
    if configured_repo != repo:
        print(
            f"ERROR: candidate repository identity {configured_repo!r} differs from git origin {repo!r}"
        )
        return 2

    try:
        metadata = gh_json(["api", f"repos/{repo}"])
        default_branch = metadata.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch:
            raise RuntimeError("GitHub repository has no default branch")
        commit = gh_json(["api", f"repos/{repo}/commits/{default_branch}"])
        prs = gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                "number,title,headRefName,headRefOid,isDraft,updatedAt,statusCheckRollup",
            ]
        )
    except Exception as exc:
        print(f"ERROR: cannot reconcile GitHub state: {exc}")
        return 2

    proposed = dict(state)
    proposed["generated_or_reconciled_at"] = dt.datetime.now(
        dt.timezone.utc
    ).isoformat()
    proposed["repository_head"] = commit.get("sha")
    durable_done: set[str] = set()
    durable_view: dict = {}

    if ledger_enabled():
        try:
            events = list_events()
            # One expensive replay for the entire reconciliation pass. Per-PR
            # authors/gates are projected from this result without re-verifying
            # historical MERGED events for each active lease.
            durable_view = lifecycle.derive_lifecycle(
                events,
                None,
                durable=True,
            )
            proposed["active_leases"] = durable_view.get(
                "active_leases", []
            )
            durable_done = set(
                durable_view.get("verified_merged_work_units", [])
            )
            conflicts = durable_view.get(
                "integrity_conflicts",
                durable_view.get("conflicts", []),
            )
            if conflicts:
                proposed["open_blockers"] = [
                    *proposed.get("open_blockers", []),
                    {"type": "ledger_conflict", "details": conflicts},
                ]
        except Exception as exc:
            print(f"ERROR: cannot reconcile durable ledger: {exc}")
            return 2

    active = [
        item
        for item in proposed.get("active_leases", [])
        if item.get("status") == "active"
        and item.get("role") == "implementation"
    ]
    pr_by_number = {pr.get("number"): pr for pr in prs}
    existing_streams = {
        stream.get("lease_id"): stream
        for stream in proposed.get("active_streams", [])
        if isinstance(stream, dict)
    }
    streams: list[dict] = []
    leased_prs: set[int] = set()
    authors_by_pr = durable_view.get("material_authors_by_pr", {})
    gates_by_pr = durable_view.get("gates_by_pr", {})

    for lease in active:
        lease_id = lease.get("id")
        pr_number = lease.get("pr")
        if isinstance(pr_number, int):
            leased_prs.add(pr_number)
        live = pr_by_number.get(pr_number)
        stream = dict(existing_streams.get(lease_id, {}))
        stream.update(
            {
                "work_unit": lease.get("work_unit"),
                "lease_id": lease_id,
                "actor": lease.get("actor"),
                "branch": lease.get("branch"),
                "pr": pr_number,
                "expires_at": lease.get("expires_at"),
                "last_progress_head": lease.get("last_progress_head"),
            }
        )
        if live:
            stream["head"] = live.get("headRefOid")
            stream["status"] = (
                "DRAFT" if live.get("isDraft") else "ACTIVE"
            )
        else:
            stream["head"] = None
            stream["status"] = (
                "PR_CLOSED_OR_MISSING"
                if pr_number is not None
                else "NO_PR"
            )

        if ledger_enabled() and isinstance(pr_number, int):
            authors = authors_by_pr.get(pr_number)
            if authors is None:
                authors = authors_by_pr.get(str(pr_number), [])
            gate = gates_by_pr.get(pr_number)
            if gate is None:
                gate = gates_by_pr.get(str(pr_number))
            stream["material_authors"] = list(authors or [])
            if (
                gate
                and live
                and gate.get("sha") != live.get("headRefOid")
            ):
                gate = dict(gate)
                gate["stale"] = True
                gate.setdefault("stale_reasons", []).append(
                    "head_changed"
                )
            stream["gate"] = gate
        else:
            stream.setdefault("material_authors", [])
            stream.setdefault("gate", None)
        streams.append(stream)

    proposed["active_streams"] = streams
    unleased_prs = [
        pr for pr in prs if pr.get("number") not in leased_prs
    ]
    proposed["unleased_open_prs"] = [
        {
            "number": pr.get("number"),
            "head": pr.get("headRefOid"),
            "branch": pr.get("headRefName"),
            "draft": pr.get("isDraft"),
        }
        for pr in unleased_prs
    ]

    ready_count = sum(
        1
        for wu in queue.get("work_units", [])
        if wu.get("status") == "READY"
        and wu.get("id") not in durable_done
    )
    proposed["ready_work_count"] = ready_count
    plan = select_parallel_set(
        queue.get("work_units", []),
        planning,
        active,
        durable_done,
    )
    proposed["safe_start_candidates"] = [
        str(item.get("id")) for item in plan.get("selected", [])
    ]

    if len(streams) == 1:
        stream = streams[0]
        proposed["current_work_unit"] = stream.get("work_unit")
        proposed["current_pr"] = stream.get("pr")
        proposed["current_pr_head"] = stream.get("head")
        proposed["current_material_authors"] = stream.get(
            "material_authors", []
        )
        proposed["current_gate"] = stream.get("gate")
    else:
        proposed["current_work_unit"] = None
        proposed["current_pr"] = None
        proposed["current_pr_head"] = None
        proposed["current_material_authors"] = []
        proposed["current_gate"] = None

    if len(streams) > 1:
        proposed["company_state"] = "ACTIVE_PARALLEL_IMPLEMENTATION"
    elif len(streams) == 1:
        proposed["company_state"] = "ACTIVE_IMPLEMENTATION"
    elif unleased_prs:
        proposed["company_state"] = "WAITING_OR_UNLEASED_PR"
    elif proposed["safe_start_candidates"]:
        proposed["company_state"] = (
            "FAULT_IDLE_WITH_READY_WORK"
            if config.get("no_idle", {}).get("enabled")
            else "READY_WORK_AVAILABLE"
        )
    elif ready_count > 0:
        proposed["company_state"] = (
            "READY_WORK_BLOCKED_BY_CONFLICT_OR_POLICY"
        )
    else:
        proposed["company_state"] = "IDLE_NO_READY_WORK"

    print(json.dumps(proposed, indent=2))
    if args.write:
        save_json(CONTROL / "state.json", proposed)
        print("Reconciled state written to .onecompany/state.json")
    else:
        print(
            "Read-only reconciliation. Re-run with --write only after reviewing "
            "the proposed cache."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
