#!/usr/bin/env python3
"""Base-trusted merge-grade assurance attestation for CompanyOS.

Candidate assurance packets nominate references; they do not define merge-grade
truth. Policy comes from the reviewed base, change/risk facts come from live
GitHub scope plus base-trusted governance, and quality facts come from artifacts
of the exact trusted workflow run.
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import math
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
GOVERNANCE_PATH = ".onecompany/governance.json"
PROFILE_ORDER = {
    "prototype": 0,
    "standard": 1,
    "production": 2,
    "high_assurance": 3,
    "regulated": 4,
}
CODE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".rs",
    ".cpp", ".cc", ".c", ".h", ".hpp", ".rb", ".php", ".swift", ".kt",
    ".kts", ".sh", ".ps1",
}
SUPPORTED_PARSER_VERSIONS = {
    "onecompany_quality_json_v1": {1},
    "cobertura_xml": {1},
    "junit_xml": {1},
    "onecompany_mutation_json_v1": {1},
}
MERGE_STATUSES = {"merge_ready", "done"}


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


def _gh_paginated_list(path: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not command_exists("gh"):
        return None, "gh CLI is required to verify trusted assurance"
    result = run(
        [
            "gh", "api", "--paginate", "--slurp", path,
            "-H", "Accept: application/vnd.github+json",
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


def _base_json(
    repo: str, path: str, base_sha: str
) -> tuple[dict[str, Any] | None, str | None, str | None]:
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


def _merge_packet_structure_errors(packet: dict[str, Any]) -> list[str]:
    """Fail closed before direct attestation performs any merge-grade evaluation."""
    errors: list[str] = []
    if packet.get("status") not in MERGE_STATUSES:
        errors.append("trusted attestation requires packet status merge_ready or done")
    if not isinstance(packet.get("work_unit"), str) or not packet.get("work_unit"):
        errors.append("trusted attestation requires work_unit")
    candidate_sha = packet.get("candidate_sha")
    if not isinstance(candidate_sha, str) or len(candidate_sha) != 40:
        errors.append("trusted attestation requires 40-character candidate_sha")
    authors = packet.get("material_authors")
    if (
        not isinstance(authors, list)
        or not authors
        or any(not isinstance(value, str) or not value for value in authors)
    ):
        errors.append("trusted attestation requires a non-empty material_authors snapshot")
    if not isinstance(packet.get("quality_profile"), str) or not packet.get("quality_profile"):
        errors.append("trusted attestation requires quality_profile")
    if not isinstance(packet.get("risk_level"), str) or not packet.get("risk_level"):
        errors.append("trusted attestation requires risk_level")
    if not isinstance(packet.get("code_change"), bool):
        errors.append("trusted attestation requires boolean code_change")
    evidence = packet.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("trusted attestation requires evidence object")
        return errors
    references = evidence.get("references")
    if not isinstance(references, list) or not references:
        errors.append("trusted attestation requires evidence.references")
    review = evidence.get("review_reference")
    if (
        not isinstance(review, dict)
        or not isinstance(review.get("review_id"), int)
        or review.get("review_id", 0) <= 0
    ):
        errors.append("trusted attestation requires positive evidence.review_reference.review_id")
    return errors


def _live_changed_paths(repo: str, pr: int) -> tuple[list[str] | None, str | None]:
    files, error = _gh_paginated_list(f"repos/{repo}/pulls/{pr}/files?per_page=100")
    if files is None:
        return None, error or "cannot read live PR files"
    paths = [str(item.get("filename")) for item in files if item.get("filename")]
    if not paths:
        return None, "live PR exposes no changed files"
    return sorted(set(paths)), None


def _path_matches(path: str, pattern: str) -> bool:
    normalized = path.replace("\\", "/")
    return fnmatch.fnmatchcase(normalized, pattern) or (
        pattern.endswith("/**")
        and normalized == pattern[:-3].rstrip("/")
    )


def _derive_scope_facts(
    paths: list[str], governance: dict[str, Any]
) -> tuple[bool, str, list[str]]:
    code_change = any(Path(path).suffix.lower() in CODE_SUFFIXES for path in paths)
    control = governance.get("control_plane", {}) if isinstance(governance, dict) else {}
    protected_patterns = [str(value) for value in control.get("protected_paths", [])]
    protected = sorted(
        path
        for path in paths
        if any(_path_matches(path, pattern) for pattern in protected_patterns)
    )
    # Protected control-plane/kernel changes are inherently high-risk. Other code
    # is at least medium-risk; documentation/data-only changes default low.
    risk_level = "high" if protected else ("medium" if code_change else "low")
    return code_change, risk_level, protected


def _parser_version_error(reference: dict[str, Any]) -> str | None:
    parser = reference.get("parser")
    if not isinstance(parser, dict):
        return "parser object is required"
    kind = str(parser.get("kind") or "")
    version = parser.get("version", 1)
    allowed = SUPPORTED_PARSER_VERSIONS.get(kind)
    if allowed is None:
        return f"unsupported evidence parser: {kind!r}"
    if not isinstance(version, int) or version not in allowed:
        return f"unsupported parser version for {kind}: {version!r}; supported={sorted(allowed)}"
    return None


def _coverage_value_errors(coverage: dict[str, float]) -> list[str]:
    errors: list[str] = []
    for metric, value in coverage.items():
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            errors.append(f"verified {metric} metric is not finite")
        elif float(value) < 0 or float(value) > 100:
            errors.append(f"verified {metric} metric {value} is outside 0..100")
    return errors


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
    governance_blob: str,
    code_change: bool,
    risk_level: str,
    changed_files: list[str],
    protected_files: list[str],
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
        "code_change": code_change,
        "risk_level": risk_level,
        "changed_files": changed_files,
        "protected_files": protected_files,
        "material_authors": sorted(
            {str(value) for value in packet.get("material_authors", []) if value}
        ),
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
        "policy_revision": (
            f"quality:{quality_blob};required-checks:{checks_blob};"
            f"governance:{governance_blob}"
        ),
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
    errors = _merge_packet_structure_errors(packet)
    if errors:
        return None, errors
    candidate_sha = str(packet["candidate_sha"])

    context, context_error = evidence_verify.verify_pr_context(
        repo, pr, candidate_sha, base_sha
    )
    if context is None:
        return None, [context_error or "live PR context could not be verified"]

    changed_files, changed_error = _live_changed_paths(repo, pr)
    if changed_files is None:
        return None, [changed_error or "live changed files could not be verified"]

    quality, quality_blob, quality_error = _base_json(repo, QUALITY_PATH, base_sha)
    checks_policy, checks_blob, checks_error = _base_json(repo, CHECKS_PATH, base_sha)
    governance, governance_blob, governance_error = _base_json(
        repo, GOVERNANCE_PATH, base_sha
    )
    if quality is None:
        errors.append(quality_error or "base-trusted quality policy is unavailable")
    if checks_policy is None:
        errors.append(checks_error or "base-trusted required-check policy is unavailable")
    if governance is None:
        errors.append(governance_error or "base-trusted governance policy is unavailable")
    if errors:
        return None, errors

    code_change, risk_level, protected_files = _derive_scope_facts(changed_files, governance)
    if packet.get("code_change") is not code_change:
        errors.append(
            f"packet code_change={packet.get('code_change')!r} disagrees with live scope {code_change}"
        )
    packet_risk = str(packet.get("risk_level") or "").lower()
    if packet_risk != risk_level:
        errors.append(
            f"packet risk_level={packet_risk!r} disagrees with base-trusted/live derived risk {risk_level!r}"
        )

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

    evidence = packet["evidence"]
    references = evidence["references"]
    verified_artifacts: list[dict[str, Any]] = []
    for reference in references:
        if not isinstance(reference, dict):
            errors.append("evidence reference must be an object")
            continue
        version_error = _parser_version_error(reference)
        if version_error:
            errors.append(version_error)
            continue
        run_id = reference.get("workflow_run_id")
        if run_id not in allowed_runs:
            errors.append(
                f"evidence {reference.get('id')} references workflow run {run_id}, "
                "which is not a base-trusted required-check run"
            )
            continue
        workflow, workflow_error = evidence_verify._workflow_run(repo, int(run_id))
        if workflow is None:
            errors.append(
                workflow_error or f"cannot resolve trusted evidence workflow run {run_id}"
            )
            continue
        expected_path = allowed_paths.get(int(run_id))
        if expected_path and workflow.get("path") != expected_path:
            errors.append(
                f"evidence workflow path {workflow.get('path')!r} does not match "
                f"base-trusted {expected_path!r}"
            )
            continue
        bound, binding_error = _workflow_binds_pr_context(
            workflow,
            pr=pr,
            candidate_sha=candidate_sha,
            base_sha=base_sha,
        )
        if not bound:
            errors.append(
                binding_error or f"trusted evidence workflow run {run_id} is not PR/base bound"
            )
            continue
        result = evidence_verify.verify_artifact_reference(
            repo, candidate_sha, base_sha, reference
        )
        verified_artifacts.append(result)
        errors.extend(str(value) for value in result.get("errors", []))

    coverage, families, aggregation_errors = evidence_verify.aggregate_extracted(
        verified_artifacts
    )
    errors.extend(aggregation_errors)
    errors.extend(_coverage_value_errors(coverage))

    profile = str(packet.get("quality_profile") or quality.get("profile") or "")
    floor_error = _profile_floor_error(quality, profile)
    if floor_error:
        errors.append(floor_error)
    else:
        errors.extend(
            evidence_verify.evaluate_quality(
                quality,
                profile,
                risk_level,
                code_change,
                coverage,
                families,
            )
        )

    review_ref = evidence.get("review_reference")
    review = evidence_verify.verify_review_reference(
        repo, pr, candidate_sha, review_ref
    )
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
        governance_blob=str(governance_blob),
        code_change=code_change,
        risk_level=risk_level,
        changed_files=changed_files,
        protected_files=protected_files,
        verdict=verdict,
    )
    return attestation, errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a base-trusted CompanyOS assurance attestation"
    )
    parser.add_argument("packet", type=Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    try:
        packet = json.loads(args.packet.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"attestation": None, "errors": [f"cannot read packet: {exc}"]}, indent=2))
        return 1
    if not isinstance(packet, dict):
        print(json.dumps({"attestation": None, "errors": ["packet must be an object"]}, indent=2))
        return 1
    attestation, errors = verify_trusted_packet(
        packet,
        repo=args.repo,
        pr=args.pr,
        base_sha=args.base_sha,
    )
    print(json.dumps({"attestation": attestation, "errors": errors}, indent=2))
    return (
        0
        if attestation is not None
        and attestation.get("verdict") == "PASS"
        and not errors
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
