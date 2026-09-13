#!/usr/bin/env python3
"""Smart, read-only-first onboarding for new, template, existing, and installed projects."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from onecompany_lib import ROOT

SOURCE_REPOSITORY = "NTinkicht/OneCompany"
FRAMEWORK_PATHS = [
    ".onecompany", "agents", "company", "patterns", "overlays", "docs", "scripts", "onecompany.py",
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md", ".github/ISSUE_TEMPLATE",
    ".github/PULL_REQUEST_TEMPLATE.md", ".github/workflows/onecompany-validate.yml",
]


def git(target: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(target), *args], text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def infer_repo(target: Path) -> str | None:
    remote = git(target, "remote", "get-url", "origin")
    if not remote: return None
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def infer_default_branch(target: Path) -> str:
    symbolic = git(target, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if symbolic and "/" in symbolic: return symbolic.split("/", 1)[1]
    branch = git(target, "branch", "--show-current")
    return branch or "main"


def detect_stack(target: Path) -> list[str]:
    checks = [
        ("Python", ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"]),
        ("Node/TypeScript", ["package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"]),
        (".NET", ["*.sln", "*.csproj"]),
        ("Java", ["pom.xml", "build.gradle", "build.gradle.kts"]),
        ("Go", ["go.mod"]),
        ("Rust", ["Cargo.toml"]),
        ("PHP", ["composer.json"]),
        ("Ruby", ["Gemfile"]),
    ]
    found: list[str] = []
    for name, patterns in checks:
        hit = False
        for pattern in patterns:
            if "*" in pattern:
                hit = any(target.glob(pattern))
            else:
                hit = (target / pattern).exists()
            if hit: break
        if hit: found.append(name)
    return found or ["Unknown / repository-agnostic"]


def detect_tests(target: Path) -> list[str]:
    candidates = ["tests", "test", "__tests__", "spec", "e2e", "integration-tests"]
    return [name for name in candidates if (target / name).exists()]


def detect_ci(target: Path) -> list[str]:
    found: list[str] = []
    workflows = target / ".github" / "workflows"
    if workflows.exists():
        count = len([p for p in workflows.iterdir() if p.is_file() and p.suffix in {".yml", ".yaml"}])
        if count: found.append(f"GitHub Actions ({count} workflow{'s' if count != 1 else ''})")
    for path, label in ((".gitlab-ci.yml", "GitLab CI"), ("azure-pipelines.yml", "Azure Pipelines"), ("Jenkinsfile", "Jenkins")):
        if (target / path).exists(): found.append(label)
    return found


def detect_mode(target: Path) -> tuple[str, str | None]:
    control = target / ".onecompany"
    if control.exists():
        config_path = control / "config.json"
        repo = None
        try:
            repo = json.loads(config_path.read_text(encoding="utf-8")).get("project", {}).get("repository")
        except Exception:
            pass
        if repo == SOURCE_REPOSITORY:
            if target.resolve() == ROOT.resolve() and infer_repo(target) == SOURCE_REPOSITORY:
                return "SOURCE_REPOSITORY", repo
            return "TEMPLATE_COPY", repo
        return "INSTALLED", repo
    meaningful = [p for p in target.iterdir() if p.name != ".git"] if target.exists() else []
    return ("ADOPT_EXISTING" if meaningful else "NEW_PROJECT"), None


def collision_paths(target: Path) -> list[str]:
    collisions: list[str] = []
    for relative in FRAMEWORK_PATHS:
        source = ROOT / relative; destination = target / relative
        if not source.exists() or not destination.exists(): continue
        if source.is_file():
            collisions.append(relative); continue
        for child in source.rglob("*"):
            if child.is_file():
                proposed = destination / child.relative_to(source)
                if proposed.exists(): collisions.append(str(proposed.relative_to(target)).replace("\\", "/"))
    return sorted(set(collisions))


def contracts(target: Path) -> dict[str, bool]:
    names = ["PRODUCT.md", "ARCHITECTURE.md", "SECURITY.md", "QUALITY.md", "DESIGN.md", "OPERATIONS.md"]
    return {name: (target / name).exists() for name in names}


def analyze(target: Path, repository: str | None = None, project_name: str | None = None, default_branch: str | None = None) -> dict[str, Any]:
    # Assessment is intentionally non-mutating. A missing target path represents
    # a NEW_PROJECT plan; the directory is created only during --apply/bootstrap.
    mode, installed_repo = detect_mode(target)
    inferred_repo = repository or infer_repo(target) or installed_repo
    result: dict[str, Any] = {
        "mode": mode,
        "target": str(target),
        "project_name": project_name or (inferred_repo.split("/", 1)[1] if inferred_repo and "/" in inferred_repo else target.name),
        "repository": inferred_repo,
        "default_branch": default_branch or infer_default_branch(target),
        "stack": detect_stack(target),
        "tests": detect_tests(target),
        "ci": detect_ci(target),
        "contracts": contracts(target),
        "safe_defaults": {
            "autonomy": "L1",
            "additional_ai_spend": 0,
            "workers_enabled": False,
            "unattended_dispatch": False,
            "supervision": "disabled/observe-only",
            "parallelism_requires_declared_non-conflicting_scope": True,
        },
    }
    result["collisions"] = collision_paths(target) if mode in {"ADOPT_EXISTING", "NEW_PROJECT"} else []
    blockers: list[str] = []
    if mode in {"ADOPT_EXISTING", "NEW_PROJECT", "TEMPLATE_COPY"} and not inferred_repo:
        blockers.append("GitHub repository could not be inferred; pass --repository OWNER/REPO")
    if result["collisions"]:
        blockers.append("Existing files collide with OneCompany framework paths; resolve them before --apply")
    if mode == "SOURCE_REPOSITORY": blockers.append("The OneCompany source repository cannot be onboarded as a target copy")
    result["blockers"] = blockers
    result["can_apply"] = mode in {"ADOPT_EXISTING", "NEW_PROJECT", "TEMPLATE_COPY"} and not blockers
    if mode == "INSTALLED":
        result["next"] = ["python onecompany.py doctor", "python onecompany.py validate", "python onecompany.py status --live", "python onecompany.py plan summary"]
    elif result["can_apply"]:
        result["next"] = ["rerun this command with --apply", "then run python onecompany.py doctor", "then run python onecompany.py validate", "then populate objective/requirements/work or use GitHub issue templates"]
    else:
        result["next"] = ["resolve blockers and rerun onboarding"]
    return result


def print_human(report: dict[str, Any]) -> None:
    print("\nOneCompany Onboarding")
    print("=" * 60)
    print(f"Mode:        {report['mode']}")
    print(f"Project:     {report['project_name']}")
    print(f"Repository:  {report.get('repository') or 'not detected'}")
    print(f"Target:      {report['target']}")
    print(f"Branch:      {report['default_branch']}")
    print(f"Stack:       {', '.join(report['stack'])}")
    print(f"Tests:       {', '.join(report['tests']) if report['tests'] else 'not detected'}")
    print(f"CI:          {', '.join(report['ci']) if report['ci'] else 'not detected'}")
    present = [name for name, exists in report['contracts'].items() if exists]
    print(f"Contracts:   {', '.join(present) if present else 'none yet'}")
    if report.get("collisions"):
        print("\nCollisions (nothing will be overwritten):")
        for item in report["collisions"][:30]: print(f"  - {item}")
        if len(report["collisions"]) > 30: print(f"  ... and {len(report['collisions']) - 30} more")
    if report.get("blockers"):
        print("\nBlockers:")
        for item in report["blockers"]: print(f"  - {item}")
    print("\nSafe starting posture:")
    print("  L1 autonomy | zero extra AI spend | workers disabled | unattended automation disabled")
    print("  Parallel work is admitted only after dependency/scope/lock/risk/capacity checks.")
    print("\nNext:")
    for item in report.get("next", []): print(f"  - {item}")


def apply(report: dict[str, Any], target: Path, initialize_contracts: bool) -> int:
    if not report.get("can_apply"):
        print("REFUSED: onboarding plan has blockers; no files changed")
        return 2
    repository = report["repository"]; project_name = report["project_name"]; default_branch = report["default_branch"]
    if report["mode"] == "TEMPLATE_COPY":
        command = [sys.executable, str(target / "onecompany.py"), "init", "--repository", repository, "--project-name", project_name, "--default-branch", default_branch]
        if initialize_contracts: command.append("--initialize-contracts")
        result = subprocess.run(command, cwd=str(target), text=True, check=False)
        return result.returncode
    command = [sys.executable, str(ROOT / "onecompany.py"), "bootstrap", "--target", str(target), "--repository", repository, "--project-name", project_name, "--default-branch", default_branch]
    if initialize_contracts: command.append("--initialize-contracts")
    result = subprocess.run(command, cwd=str(ROOT), text=True, check=False)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess or apply OneCompany onboarding")
    parser.add_argument("--target", default=".")
    parser.add_argument("--repository"); parser.add_argument("--project-name"); parser.add_argument("--default-branch")
    parser.add_argument("--apply", action="store_true", help="Apply the displayed safe onboarding plan")
    parser.add_argument("--no-contracts", action="store_true", help="Do not initialize missing root project contracts")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(); target = Path(args.target).resolve()
    report = analyze(target, args.repository, args.project_name, args.default_branch)
    if args.json: print(json.dumps(report, indent=2))
    else: print_human(report)
    if not args.apply: return 0 if not report.get("blockers") else 2
    return apply(report, target, not args.no_contracts)


if __name__ == "__main__":
    sys.exit(main())
