#!/usr/bin/env python3
"""Read-only audit of GitHub repository controls relevant to OneCompany."""
from __future__ import annotations

import json
import sys

from onecompany_lib import CONTROL, command_exists, load_json, run


def gh_api(path: str) -> tuple[int, object | None, str]:
    result = run(["gh", "api", path, "-H", "Accept: application/vnd.github+json"])
    if result.returncode != 0:
        return result.returncode, None, (result.stderr or result.stdout).strip()
    try:
        return 0, json.loads(result.stdout), ""
    except json.JSONDecodeError:
        return 1, None, "GitHub CLI returned non-JSON output"


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

    warnings: list[str] = []
    print(f"OneCompany GitHub audit: {repo} default={branch}")

    code, metadata, error = gh_api(f"repos/{repo}")
    if code:
        print(f"ERROR: cannot read repository metadata: {error}")
        return 2
    assert isinstance(metadata, dict)
    print(f"OK repository visible; private={metadata.get('private')} archived={metadata.get('archived')}")
    if metadata.get("archived"):
        warnings.append("repository is archived")

    code, protection, error = gh_api(f"repos/{repo}/branches/{branch}/protection")
    if code == 0 and isinstance(protection, dict):
        print("OK classic branch protection is readable and configured")
        checks = protection.get("required_status_checks")
        reviews = protection.get("required_pull_request_reviews")
        if not checks:
            warnings.append("branch protection does not expose required status checks")
        if not reviews:
            warnings.append("branch protection does not expose required PR review settings")
    else:
        warnings.append("classic branch protection absent or unreadable; inspect repository rulesets manually")

    code, rulesets, error = gh_api(f"repos/{repo}/rulesets")
    if code == 0 and isinstance(rulesets, list):
        active = [r for r in rulesets if r.get("enforcement") == "active"]
        print(f"OK rulesets readable; active={len(active)} total={len(rulesets)}")
        if not active and not protection:
            warnings.append("no active ruleset detected and classic protection was not confirmed")
    else:
        warnings.append("rulesets could not be read with current credential; verify protections in GitHub Settings")

    code, actions, error = gh_api(f"repos/{repo}/actions/permissions/workflow")
    if code == 0 and isinstance(actions, dict):
        default_perm = actions.get("default_workflow_permissions")
        print(f"OK Actions default token permissions={default_perm}")
        if default_perm == "write":
            warnings.append("Actions GITHUB_TOKEN defaults to write; prefer read unless workflows explicitly need write")
    else:
        warnings.append("Actions default permissions could not be read; verify Settings > Actions > General")

    print("\nWarnings:")
    if warnings:
        for warning in warnings:
            print(f"WARN: {warning}")
    else:
        print("none")
    print("\nThis audit is advisory and read-only. A warning may reflect missing API permission rather than a missing control.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
