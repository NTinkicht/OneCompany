#!/usr/bin/env python3
"""Base-trusted merge-grade assurance attestation for CompanyOS.

This layer deliberately treats candidate assurance packets as *references only*.
The decision policy comes from the reviewed base revision, deterministic checks
come from the base-trusted required-check workflow, and quality facts come from
artifacts produced by that exact trusted workflow run. Candidate-authored PASS
strings or numeric coverage claims are never decision inputs.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import evidence_verify
from required_checks import evaluate_required_checks
from onecompany_lib import command_exists, run

QUALITY_PATH = ".onecompany/quality.json"
CHECKS_PATH = ".onecompany/required-checks.json"
PROFILE_ORDER = {
    "prototype": 0,
    "standard": 1,
    "production": 2,
    "high_assurance": 3,
    "regulated": 4,
}


def _gh_json(path: str) -> tuple[dict[str, Any] | None, str | None]:
    if not command_exists("gh"):
        return None, "gh CLI is required to verify trusted assurance"
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


def _base_json(repo: str, path: str, base_sha: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    encoded_path = quote(path, safe="/")
    encoded_ref = quote(base_sha, safe="")
    payload, error = _gh_json(f"repos/{repo}/contents/{encoded_path}?ref={encoded_ref}")
    if payload is None:
        return None, None, error or f"cannot load base-trusted {path}"
    blob_sha = payload.get("sha")
    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        return None, None, f"base-trusted {path} is not decodable base64 content"
    try:
        text = base64.b64decode(payload["content"]).decode("utf-8")
        value = json.loads(text)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, f"base-trusted {path} is invalid: {exc}"
    if not isinstance(value, dict):
        return None, None, f"base-trusted {path} is not an object"
    if not isinstance(blob_sha, str) or not blob_sha:
        return None, None, f"base-trusted {path} has no blob identity"
    return value, blob_sha, None


def _workflow_binds_pr_context(
    workflow: dict[str, Any],
    *,
    pr: int,
    candidate_sha: str,
    base_sha: str,
) -> tuple[bool, str | None]:
    if workflow.get("head_sha") != candidate_sha:
        return False, "trusted evidence workflow is not bound to exact candidate SHA"
    pulls = workflow.get("pull_requests")
    if not isinstance(pulls, list):
        return False, "trusted evidence workflow does not expose pull-request binding"
    for item in pulls:
        if not isinstance(item, dict) or item.get("number") != pr:
            continue
        head = (item.get("head") or {}).get("sha")
        base = (item.get("base") or {}).get("sha")
        if head == candidate_sha and base == base_sha:
            return True, None
    return False, "trusted evidence workflow is not bound to the exact PR/head/base tuple"


def _profile_floor_error(quality: dict[str, Any], packet_profile: str) -> str | None:
    minimum = str(quality.get("profile") or "")
    if packet_profile not in quality.get("profiles", {}):
        return f"unknown quality profile {packet_profile!r} in base-trusted policy"
    if minimum in PROFILE_ORDER and packet_profile in PROFILE_ORDER:
        if PROFILE_ORDER[packet_profile] < PROFILE_ORDER[minimum]:
            return f"quality profile {packet_profile} is below base-trusted minimum {minimum}"
    return None


def _attestation(
    *,
    repo: str,
    packet: dict[str, Any],
    pr: int,
    base_sha: str,
    required_checks: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    review: dict[str, Any],
    coverage: dict[str, float],
    families: dict[str, str],
    quality_blob: str,
    checks_blob: str,
    verdict: str,
) -> dict[str, Any]:
    return {
        "schema": "onecompany-assurance-attestation-v1",
        "repository": repo,
        "work_unit": str(packet.get("work_unit") or ""),
        "pr": pr,
        "head_sha": packet.get("candidate_sha"),
        "base_sha": base_sha,
        "quality_profile": packet.get("quality_profile"),
        "risk_level": packet.get("risk_level"),
        "material_authors": sorted({str(value) for value in packet.get("material_authors", []) if value}),
        "review": review,
        "required_checks": required_checks,
        "artifacts": [
            {
                "evidence_id": item.get("id"),
                "workflow_run_id": (item.get("workflow") or {}).get("id"),
                "workflow_path": (item.get("workflow") or {}).get("path"),
                "artifact_id": (item.get("artifact") or {}).get("id"),
                "artifact_name": (item.get("artifact") or {}).get("name"),
                "digest_sha256": (item.get("artifact") or {}).get("digest_sha256"),
                "parser": item.get("parser"),
            }
            for item in artifacts
        ],
        "extracted": {"coverage": coverage, "test_families": families},
        "policy_revision": f"quality:{quality_blob};required-checks:{checks_blob}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
    }


def verify_trusted_packet(
    packet: dict[str, Any],
    *,
    repo: str,
    pr: int,
    base_sha: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Verify merge-grade evidence under policy rooted in ``base_sha``."""
    errors: list[str] = []
    candidate_sha = packet.get("candidate_sha")
    if not isinstance(candidate_sha, str) or len(candidate_sha) != 40:
        return None, ["candidate_sha must be present before trusted assurance verification"]

    context, context_error = evidence_verify.verify_pr_context(repo, pr, candidate_sha, base_sha)
    if context is None:
        return None, [context_error or "live PR context could not be verified"]

    quality, quality_blob, quality_error = _base_json(repo, QUALITY_PATH, base_sha)
    checks_policy, checks_blob, checks_error = _base_json(repo, CHECKS_PATH, base_sha)
    if quality is None:
        errors.append(quality_error or "base-trusted quality policy is unavailable")
    if checks_policy is None:
        errors.append(checks_error or "base-trusted required-check policy is unavailable")
    if errors:
        return None, errors

    checks_ok, check_errors, required_check_evidence = evaluate_required_checks(
        repo, candidate_sha, trusted_ref=base_sha
    )
    if not checks_ok:
        errors.extend(check_errors)

    allowed_runs = {
        int(item["workflow_run_id"])
        for item in required_check_evidence
        if isinstance(item.get("workflow_run_id"), int)
    }
    allowed_paths = {
        int(item["workflow_run_id"]): str(item.get("workflow_path") or "")
        for item in required_check_evidence
        if isinstance(item.get("workflow_run_id"), int)
    }

    evidence = packet.get("evidence") if isinstance(packet.get("evidence"), dict) else {}
    references = evidence.get("references") if isinstance(evidence, dict) else None
    if not isinstance(references, list) or not references:
        errors.append("merge-grade packet requires evidence.references")
        references = []

    verified_artifacts: list[dict[str, Any]] = []
    for reference in references:
        if not isinstance(reference, dict):
            errors.append("evidence reference must be an object")
            continue
        run_id = reference.get("workflow_run_id")
        if run_id not in allowed_runs:
            errors.append(
                f"evidence {reference.get('id')} references workflow run {run_id}, which is not a base-trusted required-check run"
            )
            continue
        workflow, workflow_error = evidence_verify._workflow_run(repo, int(run_id))
        if workflow is None:
            errors.append(workflow_error or f"cannot resolve trusted evidence workflow run {run_id}")
            continue
        expected_path = allowed_paths.get(int(run_id))
        if expected_path and workflow.get("path") != expected_path:
            errors.append(
                f"evidence workflow path {workflow.get('path')!r} does not match base-trusted {expected_path!r}"
            )
            continue
        bound, binding_error = _workflow_binds_pr_context(
            workflow,
            pr=pr,
            candidate_sha=candidate_sha,
            base_sha=base_sha,
        )
        if not bound:
            errors.append(binding_error or f"trusted evidence workflow run {run_id} is not PR/base bound")
            continue
        result = evidence_verify.verify_artifact_reference(
            repo,
            candidate_sha,
            base_sha,
            reference,
        )
        verified_artifacts.append(result)
        errors.extend(str(value) for value in result.get("errors", []))

    coverage, families, aggregation_errors = evidence_verify.aggregate_extracted(verified_artifacts)
    errors.extend(aggregation_errors)

    profile = str(packet.get("quality_profile") or quality.get("profile") or "")
    floor_error = _profile_floor_error(quality, profile)
    if floor_error:
        errors.append(floor_error)
    else:
        errors.extend(
            evidence_verify.evaluate_quality(
                quality,
                profile,
                str(packet.get("risk_level") or "low"),
                bool(packet.get("code_change", True)),
                coverage,
                families,
            )
        )

    review_ref = evidence.get("review_reference") if isinstance(evidence, dict) else None
    if not isinstance(review_ref, dict):
        errors.append("merge-grade packet requires evidence.review_reference")
        review = {"verified": False, "errors": ["missing review_reference"]}
    else:
        review = evidence_verify.verify_review_reference(repo, pr, candidate_sha, review_ref)
        errors.extend(str(value) for value in review.get("errors", []))

    verdict = "PASS" if not errors else "UNVERIFIED"
    attestation = _attestation(
        repo=repo,
        packet=packet,
        pr=pr,
        base_sha=base_sha,
        required_checks=required_check_evidence,
        artifacts=verified_artifacts,
        review=review,
        coverage=coverage,
        families=families,
        quality_blob=str(quality_blob),
        checks_blob=str(checks_blob),
        verdict=verdict,
    )
    return attestation, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a base-trusted CompanyOS assurance attestation")
    parser.add_argument("packet", type=Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    packet = json.loads(args.packet.read_text(encoding="utf-8"))
    attestation, errors = verify_trusted_packet(
        packet,
        repo=args.repo,
        pr=args.pr,
        base_sha=args.base_sha,
    )
    print(json.dumps({"attestation": attestation, "errors": errors}, indent=2))
    return 0 if attestation is not None and attestation.get("verdict") == "PASS" and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
