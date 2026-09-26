#!/usr/bin/env python3
"""Base-trusted platform identity and privilege mapping for CompanyOS.

Authorization facts come from GitHub platform principals plus policy loaded from
protected history. Candidate-local actor/readiness files, CLI actor labels, and
caller-selected trust roots are deliberately not authorization inputs.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime
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


def _gh_paginated_list(path: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not command_exists("gh"):
        return None, "gh CLI is required for platform identity verification"
    result = run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            path,
            "-H",
            "Accept: application/vnd.github+json",
        ]
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip() or f"GitHub query failed: {path}"
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"GitHub response was not valid JSON: {exc}"
    if not isinstance(pages, list):
        pages = [pages]
    values: list[dict[str, Any]] = []
    for page in pages:
        if isinstance(page, list):
            values.extend(item for item in page if isinstance(item, dict))
        elif isinstance(page, dict):
            values.append(page)
    return values, None


def repository_owner_info(repo: str) -> tuple[dict[str, str] | None, str | None]:
    repository, error = _gh_json(f"repos/{repo}")
    owner = (repository or {}).get("owner") if repository else None
    login = owner.get("login") if isinstance(owner, dict) else None
    owner_type = owner.get("type") if isinstance(owner, dict) else None
    if not isinstance(login, str) or not login or not isinstance(owner_type, str) or not owner_type:
        return None, error or "cannot establish repository owner identity"
    return {"login": login, "type": owner_type}, None


def protected_default_branch_context(
    repo: str,
    trusted_ref: str,
    *,
    claimed_branch: str | None = None,
) -> tuple[dict[str, str] | None, list[str]]:
    """Prove an exact trust ref belongs to the live protected default branch history."""
    repository, repo_error = _gh_json(f"repos/{repo}")
    if repository is None:
        return None, [repo_error or "cannot resolve repository metadata"]
    default_branch = repository.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        return None, ["repository has no resolvable default branch"]
    errors: list[str] = []
    if claimed_branch is not None and claimed_branch != default_branch:
        errors.append(
            f"PR targets {claimed_branch!r}, not protected default branch {default_branch!r}"
        )
    encoded_branch = quote(default_branch, safe="")
    branch, branch_error = _gh_json(f"repos/{repo}/branches/{encoded_branch}")
    tip = ((branch or {}).get("commit") or {}).get("sha") if branch else None
    if not isinstance(tip, str) or not tip:
        errors.append(branch_error or "cannot resolve protected default-branch tip")
    else:
        comparison, compare_error = _gh_json(
            f"repos/{repo}/compare/{quote(trusted_ref, safe='')}...{quote(tip, safe='')}"
        )
        status = comparison.get("status") if comparison else None
        if status not in {"ahead", "identical"}:
            errors.append(
                compare_error
                or f"trusted ref {trusted_ref} is not in protected default-branch history (status={status})"
            )
    if errors:
        return None, errors
    return {"default_branch": default_branch, "tip": str(tip), "trusted_ref": trusted_ref}, []


def protected_default_branch_tip(repo: str) -> tuple[str | None, list[str]]:
    repository, repo_error = _gh_json(f"repos/{repo}")
    if repository is None:
        return None, [repo_error or "cannot resolve repository metadata"]
    default_branch = repository.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        return None, ["repository has no resolvable default branch"]
    branch, branch_error = _gh_json(
        f"repos/{repo}/branches/{quote(default_branch, safe='')}"
    )
    tip = ((branch or {}).get("commit") or {}).get("sha") if branch else None
    if not isinstance(tip, str) or not tip:
        return None, [branch_error or "cannot resolve protected default-branch tip"]
    return tip, []


def _base_policy(
    repo: str, trusted_ref: str
) -> tuple[dict[str, Any] | None, str | None, str | None, bool]:
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
        if not isinstance(authorities, list) or not authorities or any(
            not isinstance(value, str) or not value for value in authorities
        ):
            errors.append(f"identity principal {login} has invalid authorities")
            continue
        if "root" in authorities:
            roots += 1
    if roots < 1:
        errors.append("identity policy requires at least one root principal")
    return errors


def load_identity_policy(
    repo: str, trusted_ref: str
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    """Load authority mapping from protected reviewed base; bootstrap only a user owner."""
    _context, protected_errors = protected_default_branch_context(repo, trusted_ref)
    if protected_errors:
        return None, {"source": "protected-default-branch", "trusted_ref": trusted_ref}, protected_errors

    policy, blob_sha, error, missing = _base_policy(repo, trusted_ref)
    if policy is not None:
        errors = _validate_policy(policy)
        return (
            policy if not errors else None,
            {"source": "base", "blob_sha": blob_sha, "trusted_ref": trusted_ref},
            errors,
        )
    if not missing:
        return None, {"source": "base", "trusted_ref": trusted_ref}, [
            error or "base-trusted identity policy unavailable"
        ]

    owner, owner_error = repository_owner_info(repo)
    if owner is None:
        return None, {"source": "repository-owner-bootstrap", "trusted_ref": trusted_ref}, [
            owner_error or "cannot establish repository owner for identity bootstrap"
        ]
    if owner.get("type") != "User":
        return None, {"source": "repository-owner-bootstrap", "trusted_ref": trusted_ref}, [
            "identity bootstrap requires a concrete GitHub user owner; organization-owned repositories must introduce an explicit root identity under protected human review"
        ]
    owner_login = owner["login"]
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
    return bootstrap, {
        "source": "repository-owner-bootstrap",
        "trusted_ref": trusted_ref,
        "repository_owner": owner_login,
    }, []


def map_platform_login(
    policy: dict[str, Any], login: str
) -> tuple[dict[str, Any] | None, str | None]:
    matches = [
        item
        for item in policy.get("principals", [])
        if isinstance(item, dict)
        and str(item.get("login") or "").casefold() == login.casefold()
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


def current_platform_identity(
    repo: str, trusted_ref: str
) -> tuple[dict[str, Any] | None, list[str]]:
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


def pull_request_material_author_actor_ids(
    repo: str,
    pr: int,
    candidate_sha: str,
    trusted_ref: str,
) -> tuple[set[str] | None, list[str]]:
    """Map every platform commit author on the exact PR head to a trusted actor ID."""
    commits, commit_error = _gh_paginated_list(
        f"repos/{repo}/pulls/{pr}/commits?per_page=100"
    )
    if commits is None:
        return None, [commit_error or "cannot resolve PR commit authors"]
    if not commits:
        return None, ["PR exposes no commits for material-authorship verification"]
    if commits[-1].get("sha") != candidate_sha:
        return None, ["PR commit list is not bound to the exact candidate head"]
    policy, _provenance, policy_errors = load_identity_policy(repo, trusted_ref)
    if policy is None:
        return None, policy_errors
    actors: set[str] = set()
    errors: list[str] = []
    for commit in commits:
        author = commit.get("author")
        login = author.get("login") if isinstance(author, dict) else None
        sha = commit.get("sha")
        if not isinstance(login, str) or not login:
            errors.append(f"commit {sha} has no platform-resolved author login")
            continue
        identity, mapping_error = map_platform_login(policy, login)
        if identity is None:
            errors.append(mapping_error or f"commit author {login!r} is unmapped")
            continue
        actor_id = identity.get("actor_id")
        if not isinstance(actor_id, str) or not actor_id:
            errors.append(f"commit author {login!r} maps to no actor ID")
            continue
        actors.add(actor_id)
    return (actors if not errors else None), errors


MISTRAL_BINDING = re.compile(
    r"(?m)^<!-- ONECOMPANY_MISTRAL_BINDING_REVIEW_V1 "
    r"pr=([1-9][0-9]{0,5}) head=([a-f0-9]{40}) base=([a-f0-9]{40}) "
    r"run=([1-9][0-9]{0,19}) run_sha=([a-f0-9]{40}) "
    r"verdict=(PASS|FAIL) -->$"
)
MISTRAL_WORKFLOW = ".github/workflows/onecompany-mistral-exact-head-review.yml"


def verified_mistral_review_publisher(
    repo: str, pr: int, review: dict[str, Any], head: str, base: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Give binding review authority ONLY to the proven protected-main Vibe run.

    Other github-actions[bot] reviews never inherit Mistral identity. The
    reviewer remains a model author distinct from the trusted GitHub publisher.
    """
    if repo != "NTinkicht/OneCompany" or review.get("state") != "APPROVED":
        return None, ["mistral_binding_repo_or_state_invalid"]
    if (review.get("user") or {}).get("login") != "github-actions[bot]":
        return None, ["mistral_binding_publisher_invalid"]
    body = review.get("body")
    matches = MISTRAL_BINDING.findall(body) if isinstance(body, str) else []
    if len(matches) != 1:
        return None, ["mistral_binding_marker_missing_or_ambiguous"]
    target_pr, target_head, target_base, run_id, run_sha, verdict = matches[0]
    if (int(target_pr) != pr or target_head != head or target_base != base
            or verdict != "PASS" or review.get("commit_id") != head):
        return None, ["mistral_binding_target_or_verdict_mismatch"]
    run, error = _gh_json(f"repos/{repo}/actions/runs/{run_id}")
    if run is None:
        return None, [error or "mistral_binding_run_unavailable"]
    path = run.get("path")
    if path not in {
        MISTRAL_WORKFLOW,
        f"{MISTRAL_WORKFLOW}@main",
        f"{MISTRAL_WORKFLOW}@refs/heads/main",
    }:
        return None, ["mistral_binding_workflow_invalid"]
    event = run.get("event")
    event_provenance_ok = event in {"issue_comment", "workflow_run"}
    if event == "issue_comment":
        event_provenance_ok = (
            ((run.get("actor") or {}).get("login")) == "NTinkicht"
            and ((run.get("triggering_actor") or {}).get("login")) == "NTinkicht"
        )
    if any([
        not event_provenance_ok,
        run.get("head_branch") != "main",
        run.get("head_sha") != run_sha,
        run.get("status") != "completed",
        run.get("conclusion") != "success",
        ((run.get("repository") or {}).get("full_name")) != repo,
    ]):
        return None, ["mistral_binding_run_provenance_invalid"]
    # Bind the platform review submission to the model workflow's execution
    # window. A previously successful unrelated run cannot be recycled later
    # as a generic Actions-bot approval of a different PR.
    try:
        submitted = datetime.fromisoformat(review["submitted_at"].replace("Z", "+00:00"))
        started = datetime.fromisoformat(
            run["run_started_at"].replace("Z", "+00:00"))
        finished = datetime.fromisoformat(
            run["updated_at"].replace("Z", "+00:00"))
        if not started <= submitted <= finished:
            raise ValueError("review_outside_run")
    except (ValueError, KeyError, AttributeError, TypeError):
        return None, ["mistral_binding_review_outside_run"]
    # A copied/replayed workflow result from a candidate branch is not trusted.
    _, errors = protected_default_branch_context(repo, run_sha)
    if errors:
        return None, ["mistral_binding_run_not_in_protected_main_history", *errors]
    return {
        "login": "github-actions[bot]",
        "actor_id": "mistral-vibe",
        "authorities": ["code_review"],
        "publisher": "github-actions[bot]",
        "provider": "github_pull_request_review",
        "verified_mistral_run_id": int(run_id),
        "verified_mistral_run_sha": run_sha,
    }, []


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
    # Never grant generic Actions-bot code-review authority through an
    # identity mapping alone: every Mistral approval must have workflow proof.
    if login == "github-actions[bot]":
        identity, binding_errors = verified_mistral_review_publisher(
            repo, pr, review, candidate_sha, trusted_ref
        )
        if identity is None:
            return None, binding_errors
        mapping_error = None
    else:
        identity, mapping_error = map_platform_login(policy, login)
    if identity is None and provenance.get("source") == "repository-owner-bootstrap":
        identity = {
            "login": login,
            "actor_id": f"github-reviewer:{login}",
            "authorities": ["code_review"],
            "bootstrap_review_only": True,
        }
        mapping_error = None
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


def require_authority(
    identity: dict[str, Any] | None,
    authority: str,
    excluded_actor_ids: set[str] | None = None,
) -> tuple[bool, list[str]]:
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
