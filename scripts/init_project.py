#!/usr/bin/env python3
"""Safely initialize a repository created from the OneCompany GitHub template."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from onecompany_lib import CONTROL, ROOT, load_json, save_json

SOURCE_REPOSITORY = "NTinkicht/OneCompany"
CONTRACTS = {
    "PRODUCT.md.template": "PRODUCT.md", "ARCHITECTURE.md.template": "ARCHITECTURE.md",
    "SECURITY.md.template": "SECURITY.md", "QUALITY.md.template": "QUALITY.md",
    "DESIGN.md.template": "DESIGN.md", "OPERATIONS.md.template": "OPERATIONS.md",
}


def git(*args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(ROOT), *args], text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def infer_repo() -> str | None:
    remote = git("remote", "get-url", "origin")
    if not remote: return None
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def infer_default_branch() -> str:
    symbolic = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return symbolic.split("/", 1)[1] if symbolic and "/" in symbolic else "main"


def reset_control_plane(project_name: str, repository: str, default_branch: str) -> None:
    config = load_json(CONTROL / "config.json")
    config["project"].update({"name": project_name, "repository": repository, "default_branch": default_branch})
    config["autonomy"]["level"] = "L1"; config["autonomy"]["continue_when_ready_work_exists"] = False
    config["safety"]["emergency_stop"] = False
    save_json(CONTROL / "config.json", config)

    actors = load_json(CONTROL / "actors.json")
    for actor in actors.get("actors", []):
        actor["enabled"] = False; actor["configured"] = False
    save_json(CONTROL / "actors.json", actors)

    readiness = load_json(CONTROL / "readiness.json")
    for item in readiness.get("actors", []):
        item["setup_state"] = "not_started"; item["verified_surfaces"] = []; item["verified_capabilities"] = []
        item["temporarily_unavailable_capabilities"] = []
        item["repository_access"] = {"read": False, "write": False, "review": False, "merge": False}
        item["unattended"] = {"configured": False, "verified": False}; item["last_verified_at"] = None; item["evidence"] = []
    save_json(CONTROL / "readiness.json", readiness)

    dispatch = load_json(CONTROL / "dispatch.json")
    for actor in dispatch.get("actors", []):
        for mechanism in actor.get("mechanisms", []):
            mechanism["configured"] = False; mechanism["evidence"] = []
    save_json(CONTROL / "dispatch.json", dispatch)

    ledger = load_json(CONTROL / "ledger.json")
    ledger["enabled"] = False; ledger["issue_number"] = None; ledger["trusted_publisher_logins"] = []
    save_json(CONTROL / "ledger.json", ledger)

    supervision = load_json(CONTROL / "supervision.json")
    supervision["enabled"] = False; supervision["mode"] = "observe_only"
    supervision["github_actions"]["enabled"] = False; supervision["github_actions"]["may_post_team_room"] = False
    supervision["github_actions"]["may_failover"] = False; supervision["github_actions"]["may_merge"] = False
    supervision["chatgpt_tasks"]["enabled"] = False; supervision["chatgpt_tasks"]["may_mutate"] = False
    supervision["coordination"]["team_room_issue_number"] = None
    save_json(CONTROL / "supervision.json", supervision)

    save_json(CONTROL / "queue.json", {"$schema": "./schemas/queue.schema.json", "schema_version": "1.1", "work_units": []})
    save_json(CONTROL / "portfolio.json", {"$schema": "./schemas/portfolio.schema.json", "schema_version": "1.0", "entities": [], "links": []})
    save_json(CONTROL / "requirements-catalog.json", {"$schema": "./schemas/requirements-catalog.schema.json", "schema_version": "1.0", "requirements": []})
    save_json(CONTROL / "state.json", {
        "$schema": "./schemas/state.schema.json", "schema_version": "1.1", "generated_or_reconciled_at": None,
        "repository_head": None, "company_state": "INITIALIZING", "current_work_unit": None, "current_pr": None,
        "current_pr_head": None, "current_material_authors": [], "active_leases": [], "active_streams": [], "current_gate": None,
        "ready_work_count": 0, "safe_start_candidates": [], "open_blockers": [], "human_decision_required": False,
        "note": "This file is a cache. Reconcile with live GitHub before consequential autonomous action. Legacy current_* fields are populated only when exactly one implementation stream is active.",
    })


def initialize_contracts() -> None:
    source = CONTROL / "templates" / "contracts"
    for template, destination_name in CONTRACTS.items():
        destination = ROOT / destination_name
        if destination.exists(): print(f"KEEP existing {destination_name}")
        else:
            shutil.copy2(source / template, destination); print(f"INIT {destination_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a repository created from the OneCompany GitHub template")
    parser.add_argument("--repository", help="Target owner/name; inferred from git origin when possible")
    parser.add_argument("--project-name", help="Target display name; defaults to repository name")
    parser.add_argument("--default-branch", help="Target default branch; inferred when possible")
    parser.add_argument("--initialize-contracts", action="store_true")
    args = parser.parse_args()

    config = load_json(CONTROL / "config.json"); current_repo = config.get("project", {}).get("repository")
    if current_repo != SOURCE_REPOSITORY:
        print(f"REFUSED: this installation already identifies as {current_repo!r}; init is only for an untouched OneCompany template copy. Use docs/UPGRADING.md for an existing company."); return 2
    repository = args.repository or infer_repo()
    if not repository or not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        print("REFUSED: cannot infer target repository; pass --repository owner/name"); return 2
    if repository == SOURCE_REPOSITORY:
        print("REFUSED: target repository must differ from the OneCompany source repository"); return 2
    project_name = args.project_name or repository.split("/", 1)[1]; default_branch = args.default_branch or infer_default_branch()
    reset_control_plane(project_name, repository, default_branch)
    if args.initialize_contracts: initialize_contracts()
    print(f"INITIALIZED OneCompany for {project_name} ({repository}, default={default_branch})")
    print("Portfolio, requirements catalog, queue, workers, dispatch paths, ledger and supervisors start empty/disabled until configured and verified.")
    print("Next: python onecompany.py validate && python onecompany.py plan summary && python onecompany.py status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
