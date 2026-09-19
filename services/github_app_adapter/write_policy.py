"""Pure, fail-closed contract for future interactive bot-authored file writes.

IMPORTANT: A Python caller-provided lease dict is NOT a trusted lease! This
policy is only one layer. The future MCP writer must first independently load
and verify trusted admission, live PR/base SHA and event history from GitHub.
Do not export a write MCP tool from this module alone.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
_SAFE_PATH = re.compile(
    r"^(?:services|scripts|tests|agents|patterns|docs|company|examples|overlays)/"
    r"[A-Za-z0-9_.\-/]+\.(?:py|md|json|yml|yaml|toml|txt|ts|tsx|js|jsx|css|html|sh|ps1)$"
)
ACTOR = "grok-4-6-interactive"
MAX_CONTENT_BYTES = 36_000
MAX_BRANCH_LENGTH = 100


class WriteRefused(RuntimeError):
    """Sanitized refusal, not a GitHub token, raw response, or secret."""


@dataclass(frozen=True)
class WriteRequest:
    actor: str
    work_unit: str
    lease_id: str
    pr_number: int
    expected_head_sha: str
    path: str
    content: str


def scoped_path(path: str, allowed: Any) -> bool:
    if not isinstance(path, str) or len(path) > 150:
        return False
    if (not _SAFE_PATH.fullmatch(path) or "//" in path or ".." in path
            or any(part.startswith(".") for part in path.split("/"))
            or any(x in path.lower() for x in (
                ".pem", ".key", ".env", "secret", "credential", "token",
            ))):
        return False
    if not isinstance(allowed, list) or not allowed:
        return False
    return any(
        isinstance(pattern, str)
        and pattern not in {"", "/", "**", "*"}
        and fnmatch.fnmatchcase(path, pattern)
        for pattern in allowed
    )


def verify_write_contract(
    *,
    request: WriteRequest,
    lease: dict[str, Any],
    work_item: dict[str, Any],
    pr: dict[str, Any],
    main_sha: str,
    config: dict[str, Any],
    now: dt.datetime,
    feature_enabled: bool,
    independently_verified_ledger: bool,
    independently_verified_base: bool,
    independently_verified_app: bool,
) -> dict[str, Any]:
    """Validate a trusted snapshot immediately BEFORE mutation, not grant authority.

    This does not authorise any write by itself: mutable GitHub PR ref must be
    rechecked and ref update must be fast-forward-only. Never accept evidence
    booleans or the lease/work_item/pr documents from a model-facing argument.
    """
    if not feature_enabled:
        raise WriteRefused("writer_disabled")
    if not (independently_verified_ledger and independently_verified_base
            and independently_verified_app):
        raise WriteRefused("writer_authority_unverified")
    if not isinstance(config, dict) or config.get("safety", {}).get("emergency_stop") is not False:
        raise WriteRefused("emergency_stop_or_config_unavailable")
    if config.get("autonomy", {}).get("level") != "L1":
        raise WriteRefused("autonomy_context_mismatch")
    repo = config.get("project", {}).get("repository")
    default = config.get("project", {}).get("default_branch")
    if repo != "NTinkicht/OneCompany" or default != "main":
        raise WriteRefused("repository_or_base_mismatch")
    if (request.actor != ACTOR or not request.lease_id
            or not isinstance(request.work_unit, str) or not request.work_unit
            or not isinstance(request.pr_number, int) or isinstance(request.pr_number, bool)
            or request.pr_number < 1
            or not isinstance(request.expected_head_sha, str)
            or not SHA.fullmatch(request.expected_head_sha)
            or not isinstance(request.content, str)
            or len(request.content.encode("utf-8")) > MAX_CONTENT_BYTES
            or "\0" in request.content):
        raise WriteRefused("write_request_invalid")
    if (not isinstance(lease, dict) or lease.get("id") != request.lease_id
            or lease.get("actor") != ACTOR or lease.get("role") != "implementation"
            or lease.get("status") != "active"
            or lease.get("work_unit") != request.work_unit
            or lease.get("pr") != request.pr_number):
        raise WriteRefused("implementation_lease_mismatch")
    branch = lease.get("branch")
    if (not isinstance(branch, str) or len(branch) > MAX_BRANCH_LENGTH
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", branch)
            or ".." in branch or branch.endswith(".lock")
            or branch == default):
        raise WriteRefused("canonical_branch_invalid")
    try:
        expiration = dt.datetime.fromisoformat(
            str(lease["expires_at"]).replace("Z", "+00:00")
        )
        now_utc = now.astimezone(dt.timezone.utc)
        if expiration.tzinfo is None or now_utc >= expiration:
            raise ValueError("expired")
    except (KeyError, TypeError, ValueError, OverflowError):
        raise WriteRefused("lease_expired_or_unknown") from None
    admission = lease.get("admission_snapshot")
    if (not isinstance(admission, dict)
            or admission.get("schema") != "onecompany-lease-admission-v1"
            or admission.get("actor") != ACTOR
            or admission.get("actor_eligible") is not True
            or admission.get("dependencies_complete") is not True
            or admission.get("trusted_ref") != main_sha):
        raise WriteRefused("lease_admission_unverified")
    if (not isinstance(work_item, dict)
            or work_item.get("id") != request.work_unit
            or work_item.get("branch") != branch
            or work_item.get("pr") != request.pr_number
            or work_item.get("status") != "READY"):
        raise WriteRefused("trusted_work_unit_binding_invalid")
    if not scoped_path(request.path, work_item.get("write_scope")):
        raise WriteRefused("path_outside_trusted_write_scope")
    if (not isinstance(pr, dict) or pr.get("number") != request.pr_number
            or pr.get("state") != "open"
            or pr.get("merged_at") is not None
            or not isinstance(pr.get("head"), dict)
            or not isinstance(pr.get("base"), dict)
            or pr["head"].get("ref") != branch
            or pr["head"].get("sha") != request.expected_head_sha
            or not isinstance(pr["head"].get("repo"), dict)
            or pr["head"]["repo"].get("full_name") != repo
            or pr["base"].get("ref") != default
            or pr["base"].get("sha") != main_sha
            or not isinstance(pr["base"].get("repo"), dict)
            or pr["base"]["repo"].get("full_name") != repo):
        raise WriteRefused("canonical_pr_head_or_base_changed")
    return {
        "repository": repo,
        "main_sha": main_sha,
        "branch": branch,
        "pr_number": request.pr_number,
        "expected_head_sha": request.expected_head_sha,
        "path": request.path,
        "max_content_bytes": MAX_CONTENT_BYTES,
        "lease_id": lease["id"],
        "work_unit": request.work_unit,
        "safe_to_recheck_before_exact_ref_cas": True,
        "authority_from_model_arguments": False,
    }
