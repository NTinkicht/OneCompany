#!/usr/bin/env python3
"""Check whether a checkout has the prerequisites and coherent CompanyOS control plane."""
from __future__ import annotations

import platform
import sys

from github_controls import inspect_enforcement
from onecompany_lib import CONTROL, ROOT, command_exists, emergency_stop_active, github_repo_from_config, load_json, run
from required_checks import required_check_names


def line(ok: bool, label: str, detail: str = "") -> None:
    print(f"[{'OK' if ok else '!!'}] {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    failures = 0
    python_ok = sys.version_info >= (3, 10)
    line(python_ok, "Python >= 3.10", platform.python_version())
    failures += 0 if python_ok else 1
    for name, required in (("git", True), ("gh", True), ("node", False), ("npm", False)):
        exists = command_exists(name)
        line(exists, name, "required for governed GitHub operation" if required else "optional/provider-dependent")
        failures += 1 if required and not exists else 0
    for path in sorted(CONTROL.glob("*.json")):
        try:
            load_json(path)
            line(True, str(path.relative_to(ROOT)), "valid JSON")
        except Exception as exc:
            line(False, str(path.relative_to(ROOT)), str(exc))
            failures += 1
    if command_exists("git"):
        result = run(["git", "rev-parse", "--is-inside-work-tree"])
        line(result.returncode == 0, "Git worktree", result.stdout.strip() or result.stderr.strip())
        failures += 0 if result.returncode == 0 else 1

    gh_authenticated = False
    if command_exists("gh"):
        auth = run(["gh", "auth", "status"])
        gh_authenticated = auth.returncode == 0
        line(gh_authenticated, "GitHub CLI authentication", "authenticated" if gh_authenticated else "not authenticated")
        failures += 0 if gh_authenticated else 1

    try:
        config = load_json(CONTROL / "config.json")
        actors = load_json(CONTROL / "actors.json")
        readiness = {item.get("actor_id"): item for item in load_json(CONTROL / "readiness.json").get("actors", [])}
        line(not emergency_stop_active(config), "Emergency stop", "off" if not emergency_stop_active(config) else "ACTIVE — autonomous mutation is intentionally frozen")
        for actor in actors.get("actors", []):
            if not actor.get("enabled"):
                continue
            actor_id = actor.get("id")
            status = readiness.get(actor_id, {})
            verified = status.get("verified_capabilities", [])
            ok = actor.get("configured") and status.get("setup_state") in {"ready", "degraded"} and bool(verified)
            line(bool(ok), f"enabled actor {actor_id}", f"state={status.get('setup_state')} verified={','.join(verified) or 'none'}")
            failures += 0 if ok else 1
    except Exception as exc:
        line(False, "actor/readiness summary", str(exc))
        failures += 1
        config = {}

    repo = github_repo_from_config(config) if isinstance(config, dict) else None
    branch = config.get("project", {}).get("default_branch", "main") if isinstance(config, dict) else "main"
    if repo and gh_authenticated:
        required = set(required_check_names())
        enforcement = inspect_enforcement(repo, branch, required)
        codeowners_exists = enforcement.get("codeowners_exists") is True
        line(codeowners_exists, "CODEOWNERS on default branch", ".github/CODEOWNERS present" if codeowners_exists else "missing")
        failures += 0 if codeowners_exists else 1
        codeowners_valid = enforcement.get("codeowners_valid") is True
        codeowners_detail = "valid owners + complete protected-path coverage" if codeowners_valid else (
            f"errors={enforcement.get('codeowners_errors', [])}; missing={enforcement.get('codeowners_missing_protected_paths', [])}"
        )
        line(codeowners_valid, "Effective CODEOWNERS", codeowners_detail)
        failures += 0 if codeowners_valid else 1
        review_ok = enforcement.get("code_owner_review_enforced") is True
        line(review_ok, "Code Owner review enforcement", "required" if review_ok else "not required by branch/ruleset protection")
        failures += 0 if review_ok else 1
        missing = enforcement.get("missing_required_checks", [])
        checks_ok = not missing
        line(checks_ok, "Manifest required-check enforcement", "all enforced" if checks_ok else f"missing live enforcement: {','.join(missing)}")
        failures += 0 if checks_ok else 1
        protection_ok = enforcement.get("enforcement_ok") is True
        line(protection_ok, "GitHub merge protection", "enforceable" if protection_ok else "NOT ENFORCEABLE — workers could bypass local CLI controls")
        failures += 0 if protection_ok else 1
    elif repo:
        line(False, "GitHub merge protection", "cannot verify without authenticated gh CLI")
        failures += 1
    else:
        line(False, "GitHub merge protection", "config.project.repository is not owner/name")
        failures += 1

    print("\nDoctor result:", "READY" if failures == 0 else f"{failures} blocking problem(s)")
    print("Next: python onecompany.py validate && python onecompany.py status --live")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
