#!/usr/bin/env python3
"""Read-only audit of live GitHub controls required by CompanyOS."""
from __future__ import annotations

import sys

from github_controls import gh_api, inspect_enforcement
from onecompany_lib import CONTROL, command_exists, load_json, run
from required_checks import required_check_names


def main() -> int:
    if not command_exists("gh"):
        print("ERROR: GitHub CLI (gh) is required for github-audit")
        return 2
    auth = run(["gh", "auth", "status"])
    if auth.returncode != 0:
        print("ERROR: gh is not authenticated")
        return 2

    config = load_json(CONTROL / "config.json")
    repo = config.get("project", {}).get("repository")
    branch = config.get("project", {}).get("default_branch", "main")
    if not isinstance(repo, str) or "/" not in repo:
        print("ERROR: set config.project.repository to owner/name first")
        return 2

    errors: list[str] = []
    warnings: list[str] = []
    print(f"CompanyOS GitHub audit: {repo} default={branch}")

    code, metadata, error = gh_api(f"repos/{repo}")
    if code:
        print(f"ERROR: cannot read repository metadata: {error}")
        return 2
    assert isinstance(metadata, dict)
    print(f"OK repository visible; private={metadata.get('private')} archived={metadata.get('archived')}")
    if metadata.get("archived"):
        errors.append("repository is archived")

    required = set(required_check_names())
    enforcement = inspect_enforcement(repo, branch, required)
    if enforcement.get("codeowners_exists"):
        print("OK CODEOWNERS exists on the default branch")
    else:
        errors.append(".github/CODEOWNERS is missing on the default branch")

    classic = enforcement.get("classic", {})
    if classic.get("configured"):
        print(
            "OK classic branch protection configured; "
            f"checks={classic.get('required_checks', [])} code_owner_review={classic.get('code_owner_review')}"
        )
    else:
        print("INFO classic branch protection not confirmed; checking active rulesets")

    rulesets = enforcement.get("rulesets", [])
    if rulesets:
        print(f"OK active applicable rulesets={len(rulesets)}")
        for item in rulesets:
            print(
                f"  ruleset {item.get('name') or item.get('id')}: "
                f"checks={item.get('required_checks', [])} code_owner_review={item.get('code_owner_review')}"
            )

    missing = enforcement.get("missing_required_checks", [])
    if missing:
        errors.append(f"manifest-required checks are not enforced on {branch}: {', '.join(missing)}")
    if not enforcement.get("code_owner_review_enforced"):
        errors.append("Code Owner review is not enforced by classic protection or an active applicable ruleset")
    if not classic.get("configured") and not rulesets:
        errors.append("no enforceable default-branch protection/ruleset was confirmed")
    if not enforcement.get("enforcement_ok"):
        errors.append("GitHub merge controls do not currently enforce the CompanyOS trusted boundary")

    code, actions, error = gh_api(f"repos/{repo}/actions/permissions/workflow")
    if code == 0 and isinstance(actions, dict):
        default_perm = actions.get("default_workflow_permissions")
        print(f"OK Actions default token permissions={default_perm}")
        if default_perm == "write":
            warnings.append("Actions GITHUB_TOKEN defaults to write; prefer read unless workflows explicitly need write")
    else:
        warnings.append("Actions default permissions could not be read with current credential")

    print("\nWarnings:")
    if warnings:
        for warning in warnings:
            print(f"WARN: {warning}")
    else:
        print("none")

    if errors:
        print("\nBlocking enforcement problems:")
        for item in errors:
            print(f"ERROR: {item}")
        print(f"\nGitHub enforcement audit FAILED ({len(errors)} blocking problem(s)).")
        return 1
    print("\nGitHub enforcement audit PASS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
