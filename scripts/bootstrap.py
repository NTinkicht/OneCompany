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

from install_identity import resolve_install_principals
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
    ".github/CODEOWNERS",
    ".github/ISSUE_TEMPLATE",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/onecompany-validate.yml",
]
CONTRACTS = {
    "PRODUCT.md.template": "PRODUCT.md",
    "ARCHITECTURE.md.template": "ARCHITECTURE.md",
    "SECURITY.md.template": "SECURITY.md",
    "QUALITY.md.template": "QUALITY.md",
    "DESIGN.md.template": "DESIGN.md",
    "OPERATIONS.md.template": "OPERATIONS.md",
}
INITIAL_STATE = {
    "$schema": "./schemas/state.schema.json",
    "schema_version": "1.1",
    "generated_or_reconciled_at": None,
    "repository_head": None,
    "company_state": "INITIALIZING",
    "current_work_unit": None,
    "current_pr": None,
    "current_pr_head": None,
    "current_material_authors": [],
    "active_leases": [],
    "active_streams": [],
    "current_gate": None,
    "ready_work_count": 0,
    "safe_start_candidates": [],
    "open_blockers": [],
    "human_decision_required": False,
    "note": (
        "This file is a cache. Reconcile with live GitHub before consequential "
        "autonomous action. Legacy current_* fields are populated only when exactly "
        "one implementation stream is active."
    ),
}


def run_git(target: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(target), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def infer_github_repo(target: Path) -> str | None:
    remote = run_git(target, "remote", "get-url", "origin")
    if not remote:
        return None
    for pattern in (
        r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$",
        r"github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
    ):
        match = re.search(pattern, remote)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return None


def infer_default_branch(target: Path) -> str:
    symbolic = run_git(target, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return symbolic.split("/", 1)[1] if symbolic and "/" in symbolic else "main"


def copy_item(source: Path, target: Path, force: bool) -> None:
    if source.is_dir():
        for child in source.rglob("*"):
            if not child.is_dir():
                copy_item(child, target / child.relative_to(source), force)
        return
    if target.exists() and not force:
        raise FileExistsError(
            f"refusing to overwrite {target}; use docs/UPGRADING.md for an existing OneCompany deployment"
        )
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


def configure_codeowners(target: Path, owner: str) -> None:
    path = target / ".github" / "CODEOWNERS"
    if not path.exists():
        raise FileNotFoundError("bootstrap copy did not contain .github/CODEOWNERS")
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?<!\S)@NTinkicht(?!\S)", owner, text)
    path.write_text(text, encoding="utf-8")


def configure_root_identity(target: Path, login: str) -> None:
    path = target / ".onecompany" / "identity.json"
    if not path.exists():
        raise FileNotFoundError("bootstrap copy did not contain .onecompany/identity.json")
    identity = json.loads(path.read_text(encoding="utf-8"))
    principals = identity.get("principals", [])
    roots = [
        item
        for item in principals
        if isinstance(item, dict) and "root" in item.get("authorities", [])
    ]
    if len(roots) != 1:
        raise ValueError(
            "template identity policy must contain exactly one root principal before bootstrap"
        )
    root = roots[0]
    if root.get("actor_id") != "human-owner":
        raise ValueError("template root principal must map to actor_id human-owner")
    root["login"] = login
    write_json(path, identity)


def initialize_control_plane(
    target: Path,
    project_name: str,
    repository: str,
    default_branch: str,
) -> None:
    config_path = target / ".onecompany" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.setdefault("project", {})["name"] = project_name
    config["project"]["repository"] = repository
    config["project"]["default_branch"] = default_branch
    write_json(config_path, config)

    # Durable coordination is installation-specific authority. Never inherit the
    # source repository's Team Room or trusted publisher identities into a fresh
    # company. A new deployment must explicitly activate its own ledger later.
    ledger_path = target / ".onecompany" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["enabled"] = False
    ledger["issue_number"] = None
    ledger["trusted_publisher_logins"] = []
    write_json(ledger_path, ledger)

    supervision_path = target / ".onecompany" / "supervision.json"
    supervision = json.loads(supervision_path.read_text(encoding="utf-8"))
    supervision["enabled"] = False
    supervision["mode"] = "observe_only"
    supervision.setdefault("coordination", {})["team_room_issue_number"] = None
    github_actions = supervision.setdefault("github_actions", {})
    github_actions["enabled"] = False
    github_actions["may_post_team_room"] = False
    github_actions["may_failover"] = False
    github_actions["may_merge"] = False
    chatgpt_tasks = supervision.setdefault("chatgpt_tasks", {})
    chatgpt_tasks["enabled"] = False
    chatgpt_tasks["may_mutate"] = False
    write_json(supervision_path, supervision)

    write_json(
        target / ".onecompany" / "queue.json",
        {
            "$schema": "./schemas/queue.schema.json",
            "schema_version": "1.1",
            "work_units": [],
        },
    )
    write_json(
        target / ".onecompany" / "portfolio.json",
        {
            "$schema": "./schemas/portfolio.schema.json",
            "schema_version": "1.0",
            "entities": [],
            "links": [],
        },
    )
    write_json(
        target / ".onecompany" / "requirements-catalog.json",
        {
            "$schema": "./schemas/requirements-catalog.schema.json",
            "schema_version": "1.0",
            "requirements": [],
            "acceptance_criteria": [],
        },
    )
    write_json(
        target / ".onecompany" / "risk-register.json",
        {
            "$schema": "./schemas/risk-register.schema.json",
            "schema_version": "1.0",
            "risks": [],
        },
    )
    write_json(target / ".onecompany" / "state.json", INITIAL_STATE)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a fresh OneCompany installation")
    parser.add_argument("--target", required=True)
    parser.add_argument("--repository")
    parser.add_argument("--project-name")
    parser.add_argument("--default-branch")
    parser.add_argument(
        "--code-owner",
        help=(
            "GitHub user/team for protected CompanyOS paths. User-owned repositories "
            "may infer the user owner; organization-owned repositories must pass this explicitly."
        ),
    )
    parser.add_argument(
        "--root-principal",
        help=(
            "Concrete GitHub user receiving human-owner/root platform authority. "
            "User-owned repositories may infer the user owner; organization-owned "
            "repositories must pass this explicitly."
        ),
    )
    parser.add_argument("--initialize-contracts", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if (target / ".onecompany").exists():
        print("ERROR: target already contains .onecompany. Use docs/UPGRADING.md.")
        return 2

    repository = args.repository or infer_github_repo(target)
    if not repository or not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        print("ERROR: cannot infer valid GitHub repository; pass --repository owner/name.")
        return 2
    project_name = args.project_name or target.name
    default_branch = args.default_branch or infer_default_branch(target)
    try:
        code_owner, root_principal = resolve_install_principals(
            repository,
            code_owner=args.code_owner,
            root_principal=args.root_principal,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    try:
        for relative in COPY_PATHS:
            source = ROOT / relative
            if source.exists():
                copy_item(source, target / relative, args.force)
        configure_codeowners(target, code_owner)
        configure_root_identity(target, root_principal)
    except (FileExistsError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2

    initialize_control_plane(target, project_name, repository, default_branch)
    if args.initialize_contracts:
        initialize_contracts(target)
    print(f"OneCompany installed into {target}")
    print(
        f"Project: {project_name}; repository: {repository}; default branch: {default_branch}; "
        f"code owner: {code_owner}; root principal: {root_principal}"
    )
    print(
        "Portfolio/requirements/acceptance-criteria/risk-register/queue/state and durable "
        "coordination bindings were reset; source work history was not copied. "
        "Unattended paths remain disabled."
    )
    print(
        "Run `python onecompany.py audit-github` after pushing to verify the selected "
        "Code Owner, concrete root user, and live protections."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
