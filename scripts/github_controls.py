#!/usr/bin/env python3
"""Read-only inspection of technical GitHub controls required by CompanyOS."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from onecompany_lib import CONTROL, ROOT, load_json, path_matches_any, run

# An independently operated GitHub App must publish the exact-head/base
# technical-review attestation. Set its vetted integration ID only after the
# App and non-author review implementation have been independently verified.
# None means NO trusted server-side review gate is installed; fail closed.
REVIEW_GATE_CONTEXT = "onecompany-independent-review"
REVIEW_GATE_APP_ID: int | None = None


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
    """Translate the GitHub ruleset fnmatch subset used for branch refs."""
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


def _ref_pattern_matches(pattern: str, branch: str) -> bool | None:
    pattern = str(pattern)
    if pattern in {"~ALL", "~DEFAULT_BRANCH"}:
        return True
    if pattern.startswith("~"):
        return None
    regex = _ref_pattern_regex(pattern)
    if regex is None:
        return None
    full_ref = f"refs/heads/{branch}"
    return bool(regex.fullmatch(full_ref) or regex.fullmatch(branch))


def _ruleset_applies_to_branch(ruleset: dict[str, Any], branch: str) -> bool:
    conditions = ruleset.get("conditions") or {}
    ref_name = conditions.get("ref_name") or {}
    includes = [str(value) for value in ref_name.get("include") or []]
    excludes = [str(value) for value in ref_name.get("exclude") or []]

    for pattern in excludes:
        matched = _ref_pattern_matches(pattern, branch)
        if matched is None:
            return False
        if matched:
            return False

    if not includes:
        return True
    include_match = False
    for pattern in includes:
        matched = _ref_pattern_matches(pattern, branch)
        if matched is None:
            return False
        include_match = include_match or matched
    return include_match


def _ruleset_has_bypass(ruleset: dict[str, Any]) -> bool:
    """Fail closed unless the applicable ruleset has no bypass principals."""
    bypass = ruleset.get("bypass_actors")
    if not isinstance(bypass, list):
        return True
    return bool(bypass)


def _classic_has_bypass(protection: dict[str, Any]) -> bool:
    """Return True unless classic protection is provably non-bypassable.

    Administrators must be subject to protection and PR bypass allowances must be
    explicitly present and empty. Missing/ambiguous fields fail closed because
    they cannot establish the non-bypassable enforcement CompanyOS claims.
    """
    enforce_admins = protection.get("enforce_admins")
    if not isinstance(enforce_admins, dict) or enforce_admins.get("enabled") is not True:
        return True
    reviews = protection.get("required_pull_request_reviews")
    if not isinstance(reviews, dict):
        return True
    allowances = reviews.get("bypass_pull_request_allowances")
    if not isinstance(allowances, dict):
        return True
    for key in ("users", "teams", "apps"):
        values = allowances.get(key)
        if not isinstance(values, list):
            return True
        if values:
            return True
    return False


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
    """Parse CODEOWNERS in file order, preserving ownerless rules."""
    rules: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].rstrip()
        if not line:
            continue
        parts = line.split()
        if not parts:
            continue
        pattern = parts[0]
        owners = [value for value in parts[1:] if value.startswith("@")]
        rules.append((pattern, owners))
    return rules


def _codeowners_pattern_regex(pattern: str) -> re.Pattern[str] | None:
    value = pattern.strip()
    if not value or value.startswith("!") or any(ch in value for ch in "[]{}"):
        return None
    anchored = value.startswith("/")
    value = value.lstrip("/")
    if value.endswith("/"):
        value += "**"

    out: list[str] = ["^" if anchored else r"^(?:.*/)?"]
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "*":
            if i + 1 < len(value) and value[i + 1] == "*":
                while i + 1 < len(value) and value[i + 1] == "*":
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


def _codeowners_pattern_matches(pattern: str, path: str) -> bool:
    regex = _codeowners_pattern_regex(pattern)
    if regex is None:
        return False
    normalized = path.replace("\\", "/").lstrip("/")
    return bool(regex.fullmatch(normalized))


def _effective_codeowners(
    rules: list[tuple[str, list[str]]], path: str
) -> list[str] | None:
    effective: list[str] | None = None
    matched = False
    for pattern, owners in rules:
        if _codeowners_pattern_matches(pattern, path):
            matched = True
            effective = owners
    return effective if matched else None


def _canonical_codeowner_pattern(protected_path: str) -> str:
    value = protected_path.lstrip("/")
    if value.endswith("/**"):
        return "/" + value[:-3].rstrip("/") + "/"
    return "/" + value


def _family_probe(protected_path: str) -> str | None:
    normalized = protected_path.replace("\\", "/").lstrip("/")
    if normalized.endswith("/**"):
        return normalized[:-3].rstrip("/") + "/__onecompany_codeowner_probe__"
    if not any(ch in normalized for ch in "*?["):
        return normalized
    return None


def _current_protected_files(patterns: list[str]) -> list[str]:
    files: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if path_matches_any(relative, patterns):
            files.append(relative)
    return sorted(set(files))


def _codeowners_coverage(text: str) -> tuple[bool, list[str]]:
    try:
        governance = load_json(CONTROL / "governance.json")
        protected = [
            str(value)
            for value in governance.get("control_plane", {}).get("protected_paths", [])
        ]
    except Exception:
        return False, ["cannot load governance protected_paths"]

    rules = _parse_codeowners(text)
    missing: list[str] = []
    for item in protected:
        canonical = _canonical_codeowner_pattern(item)
        probe = _family_probe(item)
        if probe is None:
            missing.append(canonical)
            continue
        owners = _effective_codeowners(rules, probe)
        if not owners:
            missing.append(canonical)

    for relative in _current_protected_files(protected):
        owners = _effective_codeowners(rules, relative)
        if not owners:
            missing.append("/" + relative)

    missing = sorted(set(missing))
    return not missing, missing


def inspect_enforcement(
    repo: str, branch: str, required_checks: set[str]
) -> dict[str, Any]:
    """Inspect technical default-branch checks and report review policy separately."""
    result: dict[str, Any] = {
        "repo": repo,
        "branch": branch,
        "codeowners_exists": False,
        "codeowners_valid": False,
        "codeowners_errors": [],
        "codeowners_missing_protected_paths": [],
        "classic": {
            "configured": False,
            "required_checks": [],
            "code_owner_review": False,
            "bypassable": True,
            "counted_as_enforcement": False,
        },
        "rulesets": [],
        "required_checks": sorted(required_checks),
        "missing_required_checks": sorted(required_checks),
        "review_gate_enforced": False,
        "enforcement_ok": False,
    }

    encoded_ref = quote(branch, safe="")
    code, codeowners, _ = gh_api(
        f"repos/{repo}/contents/.github/CODEOWNERS?ref={encoded_ref}"
    )
    result["codeowners_exists"] = code == 0 and isinstance(codeowners, dict)
    codeowners_text = (
        _decode_contents_payload(codeowners) if result["codeowners_exists"] else None
    )
    coverage_ok = False
    if codeowners_text is not None:
        coverage_ok, missing_coverage = _codeowners_coverage(codeowners_text)
        result["codeowners_missing_protected_paths"] = missing_coverage

    errors_code, errors_payload, errors_message = gh_api(
        f"repos/{repo}/codeowners/errors?ref={encoded_ref}"
    )
    errors: list[Any] = []
    if (
        errors_code == 0
        and isinstance(errors_payload, dict)
        and isinstance(errors_payload.get("errors"), list)
    ):
        errors = errors_payload.get("errors", [])
    elif result["codeowners_exists"]:
        errors = [{"message": errors_message or "CODEOWNERS validity could not be verified"}]
    result["codeowners_errors"] = errors
    result["codeowners_valid"] = bool(
        result["codeowners_exists"]
        and codeowners_text is not None
        and coverage_ok
        and not errors
    )

    observed_required: set[str] = set()
    owner_review_enforced = False
    review_gate_enforced = False
    code, protection, _ = gh_api(f"repos/{repo}/branches/{encoded_ref}/protection")
    if code == 0 and isinstance(protection, dict):
        checks = protection.get("required_status_checks") or {}
        contexts = {str(value) for value in checks.get("contexts", []) if value}
        contexts.update(
            str(item.get("context"))
            for item in checks.get("checks", [])
            if isinstance(item, dict) and item.get("context")
        )
        classic_review_gate = (
            isinstance(REVIEW_GATE_APP_ID, int)
            and not isinstance(REVIEW_GATE_APP_ID, bool)
            and REVIEW_GATE_APP_ID > 0
            and any(
                isinstance(item, dict)
                and item.get("context") == REVIEW_GATE_CONTEXT
                and item.get("app_id") == REVIEW_GATE_APP_ID
                for item in checks.get("checks", [])
            )
        )
        reviews = protection.get("required_pull_request_reviews") or {}
        code_owner = reviews.get("require_code_owner_reviews") is True
        bypassable = _classic_has_bypass(protection)
        result["classic"] = {
            "configured": True,
            "required_checks": sorted(contexts),
            "code_owner_review": code_owner,
            "bypassable": bypassable,
            "counted_as_enforcement": not bypassable,
        }
        if not bypassable:
            observed_required.update(contexts)
            owner_review_enforced = owner_review_enforced or code_owner
            review_gate_enforced = review_gate_enforced or classic_review_gate

    code, rulesets, _ = gh_api(f"repos/{repo}/rulesets")
    if code == 0 and isinstance(rulesets, list):
        for summary in rulesets:
            if (
                not isinstance(summary, dict)
                or summary.get("enforcement") != "active"
                or not summary.get("id")
            ):
                continue
            detail_code, detail, _ = gh_api(f"repos/{repo}/rulesets/{summary['id']}")
            if (
                detail_code != 0
                or not isinstance(detail, dict)
                or not _ruleset_applies_to_branch(detail, branch)
            ):
                continue
            contexts: set[str] = set()
            code_owner = False
            review_gate_here = False
            for rule in detail.get("rules", []):
                if not isinstance(rule, dict):
                    continue
                contexts.update(_required_contexts_from_rule(rule))
                if rule.get("type") == "required_status_checks":
                    specs = (rule.get("parameters") or {}).get("required_status_checks", [])
                    if (isinstance(REVIEW_GATE_APP_ID, int)
                        and not isinstance(REVIEW_GATE_APP_ID, bool)
                        and REVIEW_GATE_APP_ID > 0
                        and isinstance(specs, list)
                        and any(
                            isinstance(item, dict)
                            and item.get("context") == REVIEW_GATE_CONTEXT
                            and item.get("integration_id") == REVIEW_GATE_APP_ID
                            for item in specs
                        )):
                        review_gate_here = True
                if rule.get("type") == "pull_request":
                    params = rule.get("parameters") or {}
                    code_owner = (
                        code_owner or params.get("require_code_owner_review") is True
                    )
            bypass_actors = detail.get("bypass_actors")
            bypassable = _ruleset_has_bypass(detail)
            result["rulesets"].append(
                {
                    "id": detail.get("id"),
                    "name": detail.get("name"),
                    "required_checks": sorted(contexts),
                    "code_owner_review": code_owner,
                    "bypass_actors": bypass_actors if isinstance(bypass_actors, list) else None,
                    "counted_as_enforcement": not bypassable,
                    "review_gate_present": review_gate_here,
                }
            )
            if bypassable:
                continue
            if review_gate_here:
                review_gate_enforced = True
            observed_required.update(contexts)
            owner_review_enforced = owner_review_enforced or code_owner

    missing = required_checks - observed_required
    result["observed_required_checks"] = sorted(observed_required)
    result["missing_required_checks"] = sorted(missing)
    result["code_owner_review_enforced"] = owner_review_enforced
    result["review_gate_enforced"] = review_gate_enforced
    result["enforcement_ok"] = bool(
        result["codeowners_valid"] and not missing and review_gate_enforced
    )
    return result
