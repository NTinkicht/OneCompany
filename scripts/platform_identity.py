#!/usr/bin/env python3
"""Base-trusted platform identity and privilege mapping for CompanyOS.

Authorization facts come from GitHub platform principals plus a policy loaded
from the reviewed base revision.  Candidate-local actor/readiness files and CLI
actor labels are deliberately not authorization inputs.
"""
from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import quote

from onecompany_lib import command_exists, run

IDENTITY_PATH = ".onecompany/identity.json"
BOOTSTRAP_AUTHORITIES = {
    "root",
    "merge_execution",
    "protected_merge",
    "governance_change",
    "budget_change",
    "emergency_control",
    "root_rotation",
    "code_review",
}


def _gh_json(path: str) -> tuple[dict[str, Any] | None, str | None]:
    if not command_exists("gh"):
        return None, "gh CLI is required for platform identity verification"
    result = run(["gh", "api", path, "-H", "Accept: application/vnd.github+json"])
    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip() or f"GitHub query failed: {path}"
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"GitHub response was not valid JSON: {exc}"
    if not isinstance(value, dict):
        return None, f"GitHub response was not an object: {path}"
    return value, None


def _base_policy(repo: str, trusted_ref: str) -> tuple[dict[str, Any] | None, str | None, str | None, bool]:
    encoded_path = quote(IDENTITY_PATH, safe="/")
    encoded_ref = quote(trusted_ref, safe="")
    payload, error = _gh_json(f"repos/{repo}/contents/{encoded_path}?ref={encoded_ref}")
    if payload is None:
        missing = bool(error and ("404" in error or "Not Found" in error))
        return None, None, error, missing
    blob_sha = payload.get("sha")
    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        return None, None, f"base-trusted {IDENTITY_PATH} is not decodable base64 content", False
    try:
        value = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, f"base-trusted {IDENTITY_PATH} is invalid: {exc}", False
    if not isinstance(value, dict):
        return None, None, f"base-trusted {IDENTITY_PATH} is not an object", False
    if not isinstance(blob_sha, str) or not blob_sha:
        return None, None, f"base-trusted {IDENTITY_PATH} has no blob identity", False
    return value, blob_sha, None, False


def _validate_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if policy.get("trust_model") != "base-trusted-platform-principal":
        errors.append("identity policy trust_model must be base-trusted-platform-principal")
    principals = policy.get("principals")
    if not isinstance(principals, list) or not principals:
        return [*errors, "identity policy requires at least one principal mapping"]
    seen_logins: set[str] = set()
    roots = 0
    for item in principals:
        if not isinstance(item, dict):
            errors.append("identity principal mapping must be an object")
            continue
        login = item.get("login")
        actor_id = item.get("actor_id")
        authorities = item.get("authorities")
        if not isinstance(login, str) or not login:
            errors.append("identity principal login is required")
            continue
        key = login.casefold()
        if key in seen_logins:
            errors.append(f"identity principal login is ambiguous/duplicated: {login}")
        seen_logins.add(key)
        if not isinstance(actor_id, str) or not actor_id:
            errors.append(f"identity principal {login} has no actor_id")
        if not isinstance(authorities, list) or not authorities or any(not isinstance(value, str) or not value for value in authorities):
            errors.append(f"identity principal {login} has invalid authorities")
            continue
        if "root" in authorities:
            roots += 1
    if roots < 1:
        errors.append("identity policy requires at least one root principal")
    return errors


def load_identity_policy(repo: str, trusted_ref: str) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    """Load authority mapping from reviewed base; bootstrap only to repository owner.

    The bootstrap path exists solely for the first KERNEL-004 promotion, when the
    reviewed base predates identity.json. Once the file exists in base, any error
    loading/parsing it fails closed and candidate-local changes are ignored.
    """
    policy, blob_sha, error, missing = _base_policy(repo, trusted_ref)
    if policy is not None:
        errors = _validate_policy(policy)
        return (policy if not errors else None), {"source": "base", "blob_sha": blob_sha, "trusted_ref": trusted_ref}, errors
    if not missing:
        return None, {"source": "base", "trusted_ref": trusted_ref}, [error or "base-trusted identity policy unavailable"]

    repository, repo_error = _gh_json(f"repos/{repo}")
    owner_login = ((repository or {}).get("owner") or {}).get("login") if repository else None
    if repository is None or not isinstance(owner_login, str) or not owner_login:
        return None, {"source": "repository-owner-bootstrap", "trusted_ref": trusted_ref}, [repo_error or "cannot establish repository owner for identity bootstrap"]
    bootstrap = {
        "schema_version": "bootstrap",
        "trust_model": "base-trusted-platform-principal",
        "principals": [
            {
                "login": owner_login,
                "actor_id": "human-owner",
                "authorities": sorted(BOOTSTRAP_AUTHORITIES),
            }
        ],
    }
    return bootstrap, {"source": "repository-owner-bootstrap", "trusted_ref": trusted_ref, "repository_owner": owner_login}, []


def map_platform_login(policy: dict[str, Any], login: str) -> tuple[dict[str, Any] | None, str | None]:
    matches = [
        item
        for item in policy.get("principals", [])
        if isinstance(item, dict) and str(item.get("login") or "").casefold() == login.casefold()
    ]
    if len(matches) != 1:
        if not matches:
            return None, f"platform principal {login!r} is unknown"
        return None, f"platform principal {login!r} is ambiguous"
    item = matches[0]
    return {
        "login": login,
        "actor_id": item.get("actor_id"),
        "authorities": sorted({str(value) for value in item.get("authorities", []) if value}),
    }, None


def current_platform_identity(repo: str, trusted_ref: str) -> tuple[dict[str, Any] | None, list[str]]:
    user, user_error = _gh_json("user")
    login = user.get("login") if user else None
    if not isinstance(login, str) or not login:
        return None, [user_error or "authenticated GitHub principal is unavailable"]
    policy, provenance, errors = load_identity_policy(repo, trusted_ref)
    if policy is None:
        return None, errors
    identity, mapping_error = map_platform_login(policy, login)
    if identity is None:
        return None, [mapping_error or "platform principal mapping failed"]
    identity["provider"] = "github_authenticated_user"
    identity["policy_provenance"] = provenance
    return identity, []


def review_platform_identity(
    repo: str,
    pr: int,
    review_id: int,
    candidate_sha: str,
    trusted_ref: str,
    *,
    allowed_states: set[str] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    review, review_error = _gh_json(f"repos/{repo}/pulls/{pr}/reviews/{review_id}")
    if review is None:
        return None, [review_error or "platform review could not be resolved"]
    errors: list[str] = []
    commit_id = review.get("commit_id")
    state = str(review.get("state") or "").upper()
    login = ((review.get("user") or {}).get("login"))
    if commit_id != candidate_sha:
        errors.append("platform review does not target exact candidate SHA")
    accepted = allowed_states or {"APPROVED"}
    if state not in accepted:
        errors.append(f"platform review state {state or '<missing>'} is not accepted")
    if not isinstance(login, str) or not login:
        errors.append("platform review has no reviewer login")
    if errors:
        return None, errors
    policy, provenance, policy_errors = load_identity_policy(repo, trusted_ref)
    if policy is None:
        return None, policy_errors
    identity, mapping_error = map_platform_login(policy, login)
    if identity is None:
        return None, [mapping_error or "review principal mapping failed"]
    identity.update(
        {
            "provider": "github_pull_request_review",
            "review_id": review_id,
            "review_state": state,
            "review_commit_id": commit_id,
            "submitted_at": review.get("submitted_at"),
            "policy_provenance": provenance,
        }
    )
    return identity, []


def require_authority(identity: dict[str, Any] | None, authority: str, excluded_actor_ids: set[str] | None = None) -> tuple[bool, list[str]]:
    if identity is None:
        return False, ["identity_unverified"]
    reasons: list[str] = []
    actor_id = identity.get("actor_id")
    if not isinstance(actor_id, str) or not actor_id:
        reasons.append("identity_has_no_actor")
    if authority not in set(identity.get("authorities", [])):
        reasons.append(f"authority_missing:{authority}")
    if excluded_actor_ids and actor_id in excluded_actor_ids:
        reasons.append("material_author_conflict")
    return not reasons, reasons


def authorize_current_principal(
    repo: str,
    trusted_ref: str,
    authority: str,
    *,
    excluded_actor_ids: set[str] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    identity, errors = current_platform_identity(repo, trusted_ref)
    if identity is None:
        return None, errors
    ok, reasons = require_authority(identity, authority, excluded_actor_ids)
    return (identity if ok else None), reasons
