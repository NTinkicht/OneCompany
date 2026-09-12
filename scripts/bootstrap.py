#!/usr/bin/env python3
"""Install a fresh OneCompany control plane into another repository.

This is an installer, not an upgrade tool. Existing OneCompany deployments should follow docs/UPGRADING.md.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from onecompany_lib import ROOT

COPY_PATHS = [
    ".onecompany",
    "agents",
    "company",
    "patterns",
    "overlays",
    "docs",
    "scripts",
    "onecompany.py",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    ".github/ISSUE_TEMPLATE",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/onecompany-validate.yml",
]

CONTRACTS = {
    "PRODUCT.md.template": "PRODUCT.md",
    "ARCHITECTURE.md.template": "ARCHITECTURE.md",
    "SECURITY.md.template": "SECURITY.md",
    "QUALITY.md.template": "QUALITY.md",
    "OPERATIONS.md.template": "OPERATIONS.md",
}

INITIAL_STATE = {
    "$schema": "./schemas/state.schema.json",
    "schema_version": "1.0",
    "generated_or_reconciled_at": None,
    "repository_head": None,
    "company_state": "INITIALIZING",
    "current_work_unit": None,
    "current_pr": None,
    "current_pr_head": None,
    "current_material_authors": [],
    "active_leases": [],
    "current_gate": None,
    "ready_work_count": 0,
    "open_blockers": [],
    "human_decision_required": False,
    "note": "This file is a cache. Reconcile with live GitHub before consequential autonomous action.",
}


def run_git(target: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(target), *args], text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def infer_github_repo(target: Path) -> str | None:
    remote = run_git(target, "remote", "get-url", "origin")
    if not remote:
        return None
    for pattern in (r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", r"github\.com/([^/]+)/([^/]+?)(?:\.git)?$"):
        match = re.search(pattern, remote)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return None


def infer_default_branch(target: Path) -> str:
    symbolic = run_git(target, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if symbolic and "/" in symbolic:
        return symbolic.split("/", 1)[1]
    return "main"


def copy_item(source: Path, target: Path, force: bool) -> None:
    if source.is_dir():
        for child in source.rglob("*"):
            if child.is_dir():
                continue
            copy_item(child, target / child.relative_to(source), force)
        return
    if target.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {target}; use docs/UPGRADING.md for an existing OneCompany deployment")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def initialize_contracts(target: Path) -> None:
    source_dir = ROOT / ".onecompany" / "templates" / "contracts"
    for source_name, target_name in CONTRACTS.items():
        destination = target / target_name
        if destination.exists():
            print(f"KEEP existing project contract {target_name}")
            continue
        shutil.copy2(source_dir / source_name, destination)
        print(f"INIT project contract {target_name}")


def initialize_control_plane(target: Path, project_name: str, repository: str, default_branch: str) -> None:
    config_path = target / ".onecompany" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.setdefault("project", {})["name"] = project_name
    config["project"]["repository"] = repository
    config["project"]["default_branch"] = default_branch
    write_json(config_path, config)
    write_json(target / ".onecompany" / "queue.json", {
        "$schema": "./schemas/queue.schema.json",
        "schema_version": "1.0",
        "work_units": [],
    })
    write_json(target / ".onecompany" / "state.json", INITIAL_STATE)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a fresh OneCompany installation")
    parser.add_argument("--target", required=True, help="Path to target repository")
    parser.add_argument("--repository", help="GitHub owner/name; inferred from origin when possible")
    parser.add_argument("--project-name", help="Project display name; defaults to target directory name")
    parser.add_argument("--default-branch", help="Default branch; inferred from origin when possible")
    parser.add_argument("--initialize-contracts", action="store_true", help="Create missing product foundation contracts at target root")
    parser.add_argument("--force", action="store_true", help="Allow overwriting non-OneCompany file collisions during a first install")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if (target / ".onecompany").exists():
        print("ERROR: target already contains .onecompany. Bootstrap never overwrites an existing OneCompany installation; use docs/UPGRADING.md.")
        return 2

    repository = args.repository or infer_github_repo(target)
    if not repository:
        print("ERROR: cannot infer GitHub repository. Pass --repository owner/name.")
        return 2
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        print("ERROR: --repository must be owner/name")
        return 2
    project_name = args.project_name or target.name
    default_branch = args.default_branch or infer_default_branch(target)

    try:
        for relative in COPY_PATHS:
            source = ROOT / relative
            if source.exists():
                copy_item(source, target / relative, args.force)
    except FileExistsError as exc:
        print(f"ERROR: {exc}")
        return 2

    initialize_control_plane(target, project_name, repository, default_branch)
    if args.initialize_contracts:
        initialize_contracts(target)

    print(f"OneCompany installed into {target}")
    print(f"Project: {project_name}; repository: {repository}; default branch: {default_branch}")
    print("Operational queue/state were reset for the new company; OneCompany's own work history was not copied.")
    print("Unattended workflow templates remain disabled under .onecompany/templates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
