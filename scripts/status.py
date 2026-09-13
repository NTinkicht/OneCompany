#!/usr/bin/env python3
"""Show a compact, non-mutating OneCompany operational status."""
from __future__ import annotations

import argparse
import json
import sys

from onecompany_lib import CONTROL, command_exists, emergency_stop_active, github_repo_from_config, load_json, run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Also read live GitHub when gh is authenticated")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_json(CONTROL / "config.json")
    actors = load_json(CONTROL / "actors.json")
    readiness = load_json(CONTROL / "readiness.json")
    dispatch = load_json(CONTROL / "dispatch.json")
    queue = load_json(CONTROL / "queue.json")
    state = load_json(CONTROL / "state.json")
    ledger = load_json(CONTROL / "ledger.json")
    supervision = load_json(CONTROL / "supervision.json")

    enabled = [item.get("id") for item in actors.get("actors", []) if item.get("enabled")]
    ready = [item.get("actor_id") for item in readiness.get("actors", []) if item.get("setup_state") in {"ready", "degraded"} and item.get("verified_capabilities")]
    unattended = [item.get("actor_id") for item in readiness.get("actors", []) if item.get("unattended", {}).get("verified")]
    mechanisms = sum(1 for item in dispatch.get("actors", []) for mechanism in item.get("mechanisms", []) if mechanism.get("configured"))
    statuses: dict[str, int] = {}
    for wu in queue.get("work_units", []):
        statuses[wu.get("status", "UNKNOWN")] = statuses.get(wu.get("status", "UNKNOWN"), 0) + 1

    payload: dict = {
        "project": config.get("project"),
        "autonomy_level": config.get("autonomy", {}).get("level"),
        "emergency_stop": emergency_stop_active(config),
        "enabled_actors": enabled,
        "ready_or_degraded_actors": ready,
        "unattended_verified_actors": unattended,
        "configured_dispatch_mechanisms": mechanisms,
        "ledger": {"enabled": ledger.get("enabled"), "issue_number": ledger.get("issue_number"), "trusted_publishers": len(ledger.get("trusted_publisher_logins", []))},
        "supervision": {"enabled": supervision.get("enabled"), "mode": supervision.get("mode"), "team_room_issue_number": supervision.get("coordination", {}).get("team_room_issue_number")},
        "work_queue": statuses,
        "cached_state": {key: state.get(key) for key in ("company_state", "current_work_unit", "current_pr", "current_pr_head", "ready_work_count", "human_decision_required")},
    }

    if args.live:
        repo = github_repo_from_config(config)
        if repo and command_exists("gh") and run(["gh", "auth", "status"]).returncode == 0:
            pr = run(["gh", "pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "number,headRefOid,isDraft"])
            if pr.returncode == 0:
                payload["live_github"] = {"open_prs": json.loads(pr.stdout)}
            else:
                payload["live_github"] = {"error": pr.stderr.strip() or "cannot list PRs"}
        else:
            payload["live_github"] = {"error": "authenticated gh/repository unavailable"}

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"OneCompany — {payload['project'].get('name')} ({payload['project'].get('repository')})")
        print(f"Autonomy: {payload['autonomy_level']} | Emergency stop: {'ACTIVE' if payload['emergency_stop'] else 'off'}")
        print(f"Actors: {len(enabled)} enabled, {len(ready)} ready/degraded, {len(unattended)} unattended-verified")
        print(f"Dispatch: {mechanisms} configured mechanism(s) | Ledger: {'on' if payload['ledger']['enabled'] else 'off'} | Supervision: {payload['supervision']['mode']} ({'on' if payload['supervision']['enabled'] else 'off'})")
        print(f"Queue: {statuses or {'empty': 0}}")
        cached = payload["cached_state"]
        print(f"Cached state: {cached.get('company_state')} | WU={cached.get('current_work_unit')} | PR={cached.get('current_pr')} | human_decision={cached.get('human_decision_required')}")
        if "live_github" in payload:
            if "open_prs" in payload["live_github"]:
                print(f"Live GitHub: {len(payload['live_github']['open_prs'])} open PR(s)")
            else:
                print(f"Live GitHub: {payload['live_github']['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
