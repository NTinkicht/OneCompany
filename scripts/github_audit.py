#!/usr/bin/env python3
"""Read-only audit of live GitHub controls required by CompanyOS."""
from __future__ import annotations

import sys

from github_controls import gh_api, inspect_enforcement
from onecompany_lib import CONTROL, command_exists, load_json, run
from required_checks import required_check_names


def _audit_identity_principals(errors: list[str]) -> None:
    identity = load_json(CONTROL / "identity.json")
    principals = identity.get("principals", [])
    if not isinstance(principals, list) or not principals:
        errors.append("identity.json has no platform principals")
        return

    root_count = 0
    for item in principals:
        if not isinstance(item, dict):
            errors.append("identity.json contains a non-object principal")
            continue
        login = item.get("login")
        authorities = item.get("authorities", [])
        if not isinstance(login, str) or not login:
            errors.append("identity principal has no GitHub login")
            continue
        code, user, error = gh_api(f"users/{login}")
        if code != 0 or not isinstance(user, dict):
            errors.append(
                f"identity principal {login!r} does not resolve through GitHub: {error}"
            )
            continue
        resolved_type = user.get("type")
        if "root" in authorities:
            root_count += 1
            if resolved_type != "User":
                errors.append(
                    f"root principal {login!r} resolves as GitHub type {resolved_type!r}, not a concrete User"
                )
            else:
                print(f"OK root principal @{login} resolves to a concrete GitHub user")
        else:
            print(
                f"OK identity principal @{login} resolves through GitHub as {resolved_type or 'unknown type'}"
            )
    if root_count < 1:
        errors.append("identity policy has no principal with root authority")


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
    print(
        f"OK repository visible; private={metadata.get('private')} archived={metadata.get('archived')}"
    )
    if metadata.get("archived"):
        errors.append("repository is archived")
    live_default = metadata.get("default_branch")
    if live_default != branch:
        errors.append(
            f"configured default branch {branch!r} differs from GitHub default branch {live_default!r}"
        )

    _audit_identity_principals(errors)

    required = set(required_check_names())
    enforcement = inspect_enforcement(repo, branch, required)
    if enforcement.get("codeowners_exists"):
        print("OK CODEOWNERS exists on the default branch")
    else:
        errors.append(".github/CODEOWNERS is missing on the default branch")

    if enforcement.get("codeowners_valid"):
        print(
            "OK CODEOWNERS owners are valid and every protected CompanyOS path family is covered"
        )
    else:
        missing_paths = enforcement.get("codeowners_missing_protected_paths", [])
        live_errors = enforcement.get("codeowners_errors", [])
        if missing_paths:
            errors.append(
                "CODEOWNERS does not cover protected paths: "
                + ", ".join(str(value) for value in missing_paths)
            )
        if live_errors:
            errors.append(
                "GitHub reports CODEOWNERS errors or validity could not be verified: "
                f"{live_errors}"
            )
        if enforcement.get("codeowners_exists") and not missing_paths and not live_errors:
            errors.append("CODEOWNERS validity could not be established")

    classic = enforcement.get("classic", {})
    if classic.get("configured"):
        print(
            "OK classic branch protection configured; "
            f"checks={classic.get('required_checks', [])} "
            f"code_owner_review={classic.get('code_owner_review')}"
        )
    else:
        print("INFO classic branch protection not confirmed; checking active rulesets")

    rulesets = enforcement.get("rulesets", [])
    if rulesets:
        print(f"OK active applicable rulesets={len(rulesets)}")
        for item in rulesets:
            print(
                f"  ruleset {item.get('name') or item.get('id')}: "
                f"checks={item.get('required_checks', [])} "
                f"code_owner_review={item.get('code_owner_review')}"
            )

    missing = enforcement.get("missing_required_checks", [])
    if missing:
        errors.append(
            f"manifest-required checks are not enforced on {branch}: {', '.join(missing)}"
        )
    print("INFO Code Owner review is optional for routine technical PRs; independent non-author technical review is checked by OneCompany")
    if not enforcement.get("review_gate_enforced"):
        errors.append(
            "no pinned independent-review GitHub App check is required server-side; "
            "checks-only CI cannot enforce exact-head non-author review"
        )
    if not classic.get("configured") and not rulesets:
        errors.append("no enforceable default-branch protection/ruleset was confirmed")
    if not enforcement.get("enforcement_ok"):
        errors.append(
            "GitHub merge controls do not currently enforce the CompanyOS trusted boundary"
        )

    code, actions, _error = gh_api(f"repos/{repo}/actions/permissions/workflow")
    if code == 0 and isinstance(actions, dict):
        default_perm = actions.get("default_workflow_permissions")
        print(f"OK Actions default token permissions={default_perm}")
        if default_perm == "write":
            warnings.append(
                "Actions GITHUB_TOKEN defaults to write; prefer read unless workflows explicitly need write"
            )
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
