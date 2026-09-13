#!/usr/bin/env python3
"""Read-only inspection of live GitHub controls required by CompanyOS."""
from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib.parse import quote

from onecompany_lib import CONTROL, load_json, run


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


def _ref_pattern_regex(pattern: str) -> re.Pattern[str] | None:
    """Translate the GitHub ruleset fnmatch subset used for branch refs.

    Single `*` does not cross `/`; `**` may. Character classes and other
    extensions are deliberately not guessed: unsupported constructs return None
    so an ambiguous ruleset is not counted as protection.
    """
    if any(ch in pattern for ch in "[]{}"):
        return None
    out: list[str] = ["^"]
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                while i + 1 < len(pattern) and pattern[i + 1] == "*":
                    i += 1
                out.append(".*")
            else:
                out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def _ref_pattern_matches(pattern: str, branch: str) -> bool:
    pattern = str(pattern)
    if pattern == "~ALL":
        return True
    if pattern == "~DEFAULT_BRANCH":
        return True
    if pattern.startswith("~"):
        return False
    regex = _ref_pattern_regex(pattern)
    if regex is None:
        return False
    full_ref = f"refs/heads/{branch}"
    return bool(regex.fullmatch(full_ref) or regex.fullmatch(branch))


def _ruleset_applies_to_branch(ruleset: dict[str, Any], branch: str) -> bool:
    conditions = ruleset.get("conditions") or {}
    ref_name = conditions.get("ref_name") or {}
    includes = [str(value) for value in ref_name.get("include") or []]
    excludes = [str(value) for value in ref_name.get("exclude") or []]
    if any(_ref_pattern_matches(pattern, branch) for pattern in excludes):
        return False
    if not includes:
        return True
    return any(_ref_pattern_matches(pattern, branch) for pattern in includes)


def _decode_contents_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        return None
    content = payload.get("content")
    if not isinstance(content, str):
        return None
    try:
        return base64.b64decode(content).decode("utf-8")
    except Exception:
        return None


def _parse_codeowners(text: str) -> list[tuple[str, list[str]]]:
    rules: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern = parts[0]
        owners = [value for value in parts[1:] if value.startswith("@")]
        if owners:
            rules.append((pattern, owners))
    return rules


def _canonical_codeowner_pattern(protected_path: str) -> str:
    value = protected_path.lstrip("/")
    if value.endswith("/**"):
        return "/" + value[:-3].rstrip("/") + "/"
    return "/" + value


def _codeowners_coverage(text: str) -> tuple[bool, list[str]]:
    """Require explicit ownership for every CompanyOS protected path family.

    CompanyOS intentionally uses a canonical CODEOWNERS form instead of trying
    to reinterpret all gitignore-style equivalences. This makes coverage
    machine-auditable and avoids broad rules silently losing precedence later.
    """
    try:
        governance = load_json(CONTROL / "governance.json")
        protected = governance.get("control_plane", {}).get("protected_paths", [])
    except Exception:
        return False, ["cannot load governance protected_paths"]
    rules = {pattern: owners for pattern, owners in _parse_codeowners(text)}
    missing: list[str] = []
    for item in protected:
        canonical = _canonical_codeowner_pattern(str(item))
        alternatives = {canonical}
        if canonical.endswith("/"):
            alternatives.add(canonical + "**")
        if not any(pattern in rules and rules[pattern] for pattern in alternatives):
            missing.append(canonical)
    return not missing, missing


def inspect_enforcement(repo: str, branch: str, required_checks: set[str]) -> dict[str, Any]:
    """Inspect whether the default branch has non-bypassable review/check controls.

    Classic branch protection or an active ruleset may satisfy the enforcement
    requirement. CODEOWNERS must exist, parse without live GitHub errors, and
    explicitly cover every CompanyOS protected path family.
    """
    result: dict[str, Any] = {
        "repo": repo,
        "branch": branch,
        "codeowners_exists": False,
        "codeowners_valid": False,
        "codeowners_errors": [],
        "codeowners_missing_protected_paths": [],
        "classic": {"configured": False, "required_checks": [], "code_owner_review": False},
        "rulesets": [],
        "required_checks": sorted(required_checks),
        "missing_required_checks": sorted(required_checks),
        "enforcement_ok": False,
    }

    encoded_ref = quote(branch, safe="")
    code, codeowners, _ = gh_api(f"repos/{repo}/contents/.github/CODEOWNERS?ref={encoded_ref}")
    result["codeowners_exists"] = code == 0 and isinstance(codeowners, dict)
    codeowners_text = _decode_contents_payload(codeowners) if result["codeowners_exists"] else None
    coverage_ok = False
    if codeowners_text is not None:
        coverage_ok, missing_coverage = _codeowners_coverage(codeowners_text)
        result["codeowners_missing_protected_paths"] = missing_coverage

    errors_code, errors_payload, errors_message = gh_api(f"repos/{repo}/codeowners/errors?ref={encoded_ref}")
    errors: list[Any] = []
    if errors_code == 0 and isinstance(errors_payload, dict) and isinstance(errors_payload.get("errors"), list):
        errors = errors_payload.get("errors", [])
    elif result["codeowners_exists"]:
        errors = [{"message": errors_message or "CODEOWNERS validity could not be verified"}]
    result["codeowners_errors"] = errors
    result["codeowners_valid"] = bool(result["codeowners_exists"] and codeowners_text is not None and coverage_ok and not errors)

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
    result["enforcement_ok"] = bool(result["codeowners_valid"] and owner_review_enforced and not missing)
    return result
