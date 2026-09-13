#!/usr/bin/env python3
"""Read-only inspection of live GitHub controls required by CompanyOS."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from onecompany_lib import run


def gh_api(path: str) -> tuple[int, Any | None, str]:
    result = run(["gh", "api", path, "-H", "Accept: application/vnd.github+json"])
    if result.returncode != 0:
        return result.returncode, None, (result.stderr or result.stdout).strip()
    try:
        return 0, json.loads(result.stdout), ""
    except json.JSONDecodeError:
        return 1, None, "GitHub CLI returned non-JSON output"


def _required_contexts_from_rule(rule: dict[str, Any]) -> set[str]:
    if rule.get("type") != "required_status_checks":
        return set()
    params = rule.get("parameters") or {}
    return {
        str(item.get("context"))
        for item in params.get("required_status_checks", [])
        if isinstance(item, dict) and item.get("context")
    }


def _ruleset_applies_to_branch(ruleset: dict[str, Any], branch: str) -> bool:
    conditions = ruleset.get("conditions") or {}
    ref_name = conditions.get("ref_name") or {}
    includes = set(ref_name.get("include") or [])
    excludes = set(ref_name.get("exclude") or [])
    candidates = {branch, f"refs/heads/{branch}", "~DEFAULT_BRANCH", "~ALL"}
    if candidates & excludes:
        return False
    return not includes or bool(candidates & includes)


def inspect_enforcement(repo: str, branch: str, required_checks: set[str]) -> dict[str, Any]:
    """Inspect whether the default branch has non-bypassable review/check controls.

    Classic branch protection or an active ruleset may satisfy the enforcement
    requirement, but CODEOWNERS must exist and Code Owner review must be required.
    """
    result: dict[str, Any] = {
        "repo": repo,
        "branch": branch,
        "codeowners_exists": False,
        "classic": {"configured": False, "required_checks": [], "code_owner_review": False},
        "rulesets": [],
        "required_checks": sorted(required_checks),
        "missing_required_checks": sorted(required_checks),
        "enforcement_ok": False,
    }

    encoded_ref = quote(branch, safe="")
    code, codeowners, _ = gh_api(f"repos/{repo}/contents/.github/CODEOWNERS?ref={encoded_ref}")
    result["codeowners_exists"] = code == 0 and isinstance(codeowners, dict)

    observed_required: set[str] = set()
    owner_review_enforced = False
    code, protection, _ = gh_api(f"repos/{repo}/branches/{encoded_ref}/protection")
    if code == 0 and isinstance(protection, dict):
        checks = protection.get("required_status_checks") or {}
        contexts = {str(value) for value in checks.get("contexts", []) if value}
        contexts.update(
            str(item.get("context"))
            for item in checks.get("checks", [])
            if isinstance(item, dict) and item.get("context")
        )
        reviews = protection.get("required_pull_request_reviews") or {}
        code_owner = reviews.get("require_code_owner_reviews") is True
        observed_required.update(contexts)
        owner_review_enforced = owner_review_enforced or code_owner
        result["classic"] = {
            "configured": True,
            "required_checks": sorted(contexts),
            "code_owner_review": code_owner,
        }

    code, rulesets, _ = gh_api(f"repos/{repo}/rulesets")
    if code == 0 and isinstance(rulesets, list):
        for summary in rulesets:
            if not isinstance(summary, dict) or summary.get("enforcement") != "active" or not summary.get("id"):
                continue
            detail_code, detail, _ = gh_api(f"repos/{repo}/rulesets/{summary['id']}")
            if detail_code != 0 or not isinstance(detail, dict) or not _ruleset_applies_to_branch(detail, branch):
                continue
            contexts: set[str] = set()
            code_owner = False
            for rule in detail.get("rules", []):
                if not isinstance(rule, dict):
                    continue
                contexts.update(_required_contexts_from_rule(rule))
                if rule.get("type") == "pull_request":
                    params = rule.get("parameters") or {}
                    code_owner = code_owner or params.get("require_code_owner_review") is True
            observed_required.update(contexts)
            owner_review_enforced = owner_review_enforced or code_owner
            result["rulesets"].append(
                {
                    "id": detail.get("id"),
                    "name": detail.get("name"),
                    "required_checks": sorted(contexts),
                    "code_owner_review": code_owner,
                }
            )

    missing = required_checks - observed_required
    result["observed_required_checks"] = sorted(observed_required)
    result["missing_required_checks"] = sorted(missing)
    result["code_owner_review_enforced"] = owner_review_enforced
    result["enforcement_ok"] = bool(result["codeowners_exists"] and owner_review_enforced and not missing)
    return result
