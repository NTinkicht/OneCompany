#!/usr/bin/env python3
"""Pinned reviewer and credential-isolation gate for L5 mutations."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

SHA40 = re.compile(r"^[0-9a-fA-F]{40}$")
POLICY_PATH = Path(__file__).resolve().parents[1] / ".l5" / "trust-policy.json"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


@dataclass(frozen=True)
class TrustPolicy:
    binding_reviewer_logins: frozenset[str]
    controller_identities: frozenset[str]
    policy_hash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TrustPolicy":
        if value.get("schema_version") != "1.0":
            raise ValueError("TRUST_POLICY_SCHEMA_INVALID")
        reviewers = value.get("binding_reviewers")
        controllers = value.get("controller_identities")
        if not isinstance(reviewers, list) or not reviewers:
            raise ValueError("TRUST_POLICY_REVIEWERS_INVALID")
        if not isinstance(controllers, list) or not controllers:
            raise ValueError("TRUST_POLICY_CONTROLLERS_INVALID")
        logins: set[str] = set()
        for reviewer in reviewers:
            if not isinstance(reviewer, Mapping):
                raise ValueError("TRUST_POLICY_REVIEWER_INVALID")
            identities = reviewer.get("github_logins")
            if not isinstance(identities, list) or not identities:
                raise ValueError("TRUST_POLICY_REVIEWER_LOGIN_INVALID")
            logins.update(_norm(actor) for actor in identities if _norm(actor))
        controller_set = {_norm(actor) for actor in controllers if _norm(actor)}
        if not controller_set or logins & controller_set:
            raise ValueError("TRUST_POLICY_IDENTITY_OVERLAP")
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return cls(frozenset(logins), frozenset(controller_set), sha256(canonical.encode()).hexdigest())


def load_trust_policy(path: Path = POLICY_PATH) -> TrustPolicy:
    """Load the human-governed policy from the trusted controller checkout."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("TRUST_POLICY_INVALID")
    return TrustPolicy.from_mapping(value)


def review_is_independent(
    review: Mapping[str, Any],
    *,
    policy: TrustPolicy,
    head_sha: str,
    base_sha: str,
    material_authors: Sequence[str],
) -> tuple[bool, tuple[str, ...]]:
    """Validate exact-state review against the pinned reviewer registry."""
    failures: list[str] = []
    if not isinstance(head_sha, str) or not SHA40.fullmatch(head_sha):
        failures.append("HEAD_SHA_INVALID")
    if not isinstance(base_sha, str) or not SHA40.fullmatch(base_sha):
        failures.append("BASE_SHA_INVALID")
    if review.get("state") != "APPROVED":
        failures.append("REVIEW_NOT_APPROVED")
    if review.get("commit_id") != head_sha:
        failures.append("REVIEW_HEAD_MISMATCH")
    if review.get("base_sha") != base_sha:
        failures.append("REVIEW_BASE_MISMATCH")
    if review.get("complete") is not True or review.get("covers_full_diff") is not True:
        failures.append("REVIEW_INCOMPLETE")
    if review.get("skipped") is not False:
        failures.append("REVIEW_SKIPPED")
    if review.get("identity_source_verified") is not True:
        failures.append("REVIEW_IDENTITY_UNVERIFIED")
    author = _norm(review.get("author"))
    if author not in policy.binding_reviewer_logins:
        failures.append("REVIEWER_NOT_IN_PINNED_REGISTRY")
    excluded = policy.controller_identities | {_norm(actor) for actor in material_authors}
    if not author or author in excluded:
        failures.append("REVIEWER_NOT_INDEPENDENT")
    return not failures, tuple(dict.fromkeys(failures))


def credential_boundary_ok(evidence: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Fail closed unless write credentials and repository-code execution are isolated."""
    expected = {
        "controller_executes_repository_code": False,
        "test_worker_has_write_token": False,
        "write_token_in_test_env": False,
        "actuator_executes_repository_code": False,
        "repo_code_runs_in_actuator": False,
        "actuator_accepts_structured_only": True,
        "credential_boundary_verified": True,
    }
    failures = [
        f"CREDENTIAL_BOUNDARY_{key.upper()}"
        for key, wanted in expected.items()
        if evidence.get(key) is not wanted
    ]
    return not failures, tuple(failures)


def trust_boundary_ok(
    evidence: Mapping[str, Any],
    *,
    policy: TrustPolicy,
    head_sha: str,
    base_sha: str,
    material_authors: Sequence[str],
) -> tuple[bool, tuple[str, ...]]:
    """Validate reviewer independence, credential isolation, and policy binding."""
    failures: list[str] = []
    review = evidence.get("review")
    credential = evidence.get("credential_boundary")
    if not isinstance(review, Mapping):
        failures.append("REVIEW_EVIDENCE_MISSING")
    else:
        failures.extend(review_is_independent(review, policy=policy, head_sha=head_sha, base_sha=base_sha, material_authors=material_authors)[1])
    if not isinstance(credential, Mapping):
        failures.append("CREDENTIAL_BOUNDARY_EVIDENCE_MISSING")
    else:
        failures.extend(credential_boundary_ok(credential)[1])
    if evidence.get("trust_policy_hash") != policy.policy_hash:
        failures.append("TRUST_POLICY_HASH_MISMATCH")
    return not failures, tuple(dict.fromkeys(failures))


def trust_boundary_from_activation(snapshot: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Evaluate the final mutation snapshot using the pinned on-disk policy."""
    head = snapshot.get("head_sha")
    base = snapshot.get("base_sha")
    material_authors = snapshot.get("material_authors")
    if not isinstance(material_authors, list):
        return False, ("MATERIAL_AUTHORSHIP_INVALID",)
    review = snapshot.get("trust_review")
    credential = snapshot.get("credential_boundary")
    evidence = {
        "review": review,
        "credential_boundary": credential,
        "trust_policy_hash": snapshot.get("trust_policy_hash"),
    }
    try:
        policy = load_trust_policy()
    except (OSError, ValueError, json.JSONDecodeError):
        return False, ("TRUST_POLICY_UNAVAILABLE",)
    return trust_boundary_ok(
        evidence,
        policy=policy,
        head_sha=str(head or ""),
        base_sha=str(base or ""),
        material_authors=[str(actor) for actor in material_authors],
    )
