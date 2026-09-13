#!/usr/bin/env python3
"""Platform-backed engineering evidence verification for CompanyOS assurance.

Candidate packets may nominate evidence references. This module resolves those
references against GitHub, downloads the referenced artifact, hashes what was
actually downloaded, parses a deliberately small deterministic format set, and
produces extracted facts. Packet-authored PASS/coverage values are never inputs
to the quality decision here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from onecompany_lib import CONTROL, command_exists, load_json, run

SUPPORTED_PARSER_VERSIONS = {
    "onecompany_quality_json_v1": {1},
    "cobertura_xml": {1},
    "junit_xml": {1},
    "onecompany_mutation_json_v1": {1},
}
SUPPORTED_PARSERS = set(SUPPORTED_PARSER_VERSIONS)


def _gh_json(path: str) -> tuple[dict[str, Any] | None, str | None]:
    if not command_exists("gh"):
        return None, "gh CLI is required to verify platform evidence"
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


def _workflow_run(repo: str, run_id: int) -> tuple[dict[str, Any] | None, str | None]:
    return _gh_json(f"repos/{repo}/actions/runs/{run_id}")


def _pull_request(repo: str, pr: int) -> tuple[dict[str, Any] | None, str | None]:
    return _gh_json(f"repos/{repo}/pulls/{pr}")


def _review(repo: str, pr: int, review_id: int) -> tuple[dict[str, Any] | None, str | None]:
    return _gh_json(f"repos/{repo}/pulls/{pr}/reviews/{review_id}")


def _artifacts_for_run(repo: str, run_id: int) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not command_exists("gh"):
        return None, "gh CLI is required to verify GitHub artifacts"
    result = run(
        [
            "gh", "api", "--paginate", "--slurp",
            f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
            "-H", "Accept: application/vnd.github+json",
        ]
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip() or "GitHub artifact query failed"
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"GitHub artifact response was not valid JSON: {exc}"
    if not isinstance(pages, list):
        pages = [pages]
    artifacts: list[dict[str, Any]] = []
    for page in pages:
        if isinstance(page, dict):
            items = page.get("artifacts", [])
            if isinstance(items, list):
                artifacts.extend(item for item in items if isinstance(item, dict))
    return artifacts, None


def _download_artifact(repo: str, run_id: int, artifact_name: str, destination: Path) -> str | None:
    if not command_exists("gh"):
        return "gh CLI is required to download GitHub artifacts"
    result = run(
        [
            "gh", "run", "download", str(run_id), "--repo", repo,
            "--name", artifact_name, "--dir", str(destination),
        ]
    )
    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip() or "GitHub artifact download failed"
    return None


def _artifact_digest(root: Path) -> tuple[str | None, list[str], str | None]:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        return None, [], "downloaded artifact contains no files"
    manifest = hashlib.sha256()
    relative_paths: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        relative_paths.append(relative)
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.update(relative.encode("utf-8"))
        manifest.update(b"\0")
        manifest.update(file_hash.encode("ascii"))
        manifest.update(b"\n")
    return manifest.hexdigest(), relative_paths, None


def _report_path(root: Path, parser: dict[str, Any]) -> tuple[Path | None, str | None]:
    value = parser.get("path")
    if not isinstance(value, str) or not value.strip():
        return None, "parser.path is required"
    candidate = (root / value).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None, "parser.path escapes the downloaded artifact"
    if not candidate.is_file():
        return None, f"parser report path does not exist: {value}"
    return candidate, None


def _parser_version_error(parser: dict[str, Any]) -> str | None:
    kind = parser.get("kind")
    allowed = SUPPORTED_PARSER_VERSIONS.get(str(kind or ""))
    if allowed is None:
        return f"unsupported evidence parser: {kind!r}"
    version = parser.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version not in allowed:
        return f"unsupported parser version for {kind}: {version!r}; supported={sorted(allowed)}"
    return None


def _percent(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    if number < 0 or number > 100:
        raise ValueError(f"{field} must be within 0..100")
    return number


def _parse_quality_json(path: Path, candidate_sha: str, base_sha: str | None) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != "onecompany-quality-evidence-v1":
        raise ValueError("quality JSON must declare schema=onecompany-quality-evidence-v1")
    if value.get("candidate_sha") != candidate_sha:
        raise ValueError("quality JSON candidate_sha does not match exact candidate head")
    if base_sha is not None and value.get("base_sha") not in {None, base_sha}:
        raise ValueError("quality JSON base_sha does not match reviewed base")

    extracted: dict[str, Any] = {"coverage": {}, "test_families": {}, "tool": value.get("tool")}
    coverage = value.get("coverage") or {}
    if not isinstance(coverage, dict):
        raise ValueError("quality JSON coverage must be an object")
    for metric in ("line", "branch", "changed_line", "mutation"):
        if metric in coverage:
            extracted["coverage"][metric] = _percent(coverage[metric], f"coverage.{metric}")

    families = value.get("test_families") or {}
    if not isinstance(families, dict):
        raise ValueError("quality JSON test_families must be an object")
    for family, result in families.items():
        status = result.get("status") if isinstance(result, dict) else result
        normalized = str(status).lower()
        if normalized not in {"pass", "fail", "skipped"}:
            raise ValueError(f"test family {family} has unsupported status {status!r}")
        extracted["test_families"][str(family)] = normalized
    return extracted


def _parse_cobertura(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    if root.tag.rsplit("}", 1)[-1] != "coverage":
        raise ValueError("Cobertura report root must be <coverage>")
    line_rate = _percent(root.attrib.get("line-rate"), "line-rate")
    branch_rate = _percent(root.attrib.get("branch-rate"), "branch-rate")
    if line_rate <= 1:
        line_rate *= 100
    if branch_rate <= 1:
        branch_rate *= 100
    return {"coverage": {"line": line_rate, "branch": branch_rate}, "test_families": {}}


def _junit_totals(element: ET.Element) -> tuple[int, int, int, int]:
    tests = int(element.attrib.get("tests", 0) or 0)
    failures = int(element.attrib.get("failures", 0) or 0)
    errors = int(element.attrib.get("errors", 0) or 0)
    skipped = int(element.attrib.get("skipped", element.attrib.get("disabled", 0)) or 0)
    if min(tests, failures, errors, skipped) < 0:
        raise ValueError("JUnit counters cannot be negative")
    if failures + errors + skipped > tests:
        raise ValueError("JUnit failure/error/skipped counters exceed tests")
    return tests, failures, errors, skipped


def _parse_junit(path: Path, family: str | None) -> dict[str, Any]:
    if not family:
        raise ValueError("JUnit parser requires parser.family")
    root = ET.parse(path).getroot()
    tag = root.tag.rsplit("}", 1)[-1]
    if tag == "testsuite":
        totals = _junit_totals(root)
    elif tag == "testsuites":
        suites = [item for item in root if item.tag.rsplit("}", 1)[-1] == "testsuite"]
        if root.attrib.get("tests") is not None:
            totals = _junit_totals(root)
        else:
            values = [_junit_totals(item) for item in suites]
            totals = tuple(sum(item[index] for item in values) for index in range(4))
    else:
        raise ValueError("JUnit report root must be <testsuite> or <testsuites>")
    tests, failures, errors, skipped = totals
    status = "pass" if failures == 0 and errors == 0 and tests > 0 else "fail"
    return {
        "coverage": {},
        "test_families": {family: status},
        "test_summary": {"tests": tests, "failures": failures, "errors": errors, "skipped": skipped},
    }


def _parse_mutation_json(path: Path, candidate_sha: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != "onecompany-mutation-evidence-v1":
        raise ValueError("mutation JSON must declare schema=onecompany-mutation-evidence-v1")
    if value.get("candidate_sha") != candidate_sha:
        raise ValueError("mutation JSON candidate_sha does not match exact candidate head")
    score = _percent(value.get("mutation_score"), "mutation_score")
    return {"coverage": {"mutation": score}, "test_families": {"mutation": "pass"}}


def parse_report(
    root: Path,
    parser: dict[str, Any],
    candidate_sha: str,
    base_sha: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    version_error = _parser_version_error(parser)
    if version_error:
        return None, version_error
    kind = str(parser.get("kind") or "")
    report, error = _report_path(root, parser)
    if report is None:
        return None, error
    try:
        if kind == "onecompany_quality_json_v1":
            return _parse_quality_json(report, candidate_sha, base_sha), None
        if kind == "cobertura_xml":
            return _parse_cobertura(report), None
        if kind == "junit_xml":
            return _parse_junit(report, parser.get("family")), None
        if kind == "onecompany_mutation_json_v1":
            return _parse_mutation_json(report, candidate_sha), None
    except (ET.ParseError, json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError) as exc:
        return None, f"cannot parse {kind} evidence: {exc}"
    return None, f"unsupported evidence parser: {kind!r}"


def verify_pr_context(repo: str, pr: int, candidate_sha: str, base_sha: str) -> tuple[dict[str, Any] | None, str | None]:
    live, error = _pull_request(repo, pr)
    if live is None:
        return None, error or "cannot read live pull request"
    head = ((live.get("head") or {}).get("sha"))
    base = ((live.get("base") or {}).get("sha"))
    if head != candidate_sha:
        return None, f"live PR head drifted: expected {candidate_sha}, observed {head}"
    if base != base_sha:
        return None, f"live PR base drifted: expected {base_sha}, observed {base}"
    if live.get("state") != "open":
        return None, f"pull request is not open (state={live.get('state')})"
    return {"head_sha": head, "base_sha": base, "state": live.get("state")}, None


def verify_artifact_reference(
    repo: str,
    candidate_sha: str,
    base_sha: str | None,
    reference: dict[str, Any],
) -> dict[str, Any]:
    """Resolve one GitHub Actions artifact reference into platform-backed facts."""
    result: dict[str, Any] = {
        "id": reference.get("id"),
        "verified": False,
        "provider": reference.get("provider"),
        "source_kind": reference.get("source_kind"),
        "candidate_sha": candidate_sha,
        "base_sha": base_sha,
        "errors": [],
    }
    if reference.get("provider") != "github_actions" or reference.get("source_kind") != "artifact":
        result["errors"].append("merge-grade artifact evidence must use provider=github_actions and source_kind=artifact")
        return result
    run_id = reference.get("workflow_run_id")
    artifact_id = reference.get("artifact_id")
    artifact_name = reference.get("artifact_name")
    parser = reference.get("parser")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
        result["errors"].append("workflow_run_id must be a positive integer")
    if not isinstance(artifact_id, int) or isinstance(artifact_id, bool) or artifact_id <= 0:
        result["errors"].append("artifact_id must be a positive integer")
    if not isinstance(artifact_name, str) or not artifact_name:
        result["errors"].append("artifact_name is required")
    if not isinstance(parser, dict):
        result["errors"].append("parser object is required")
    else:
        parser_error = _parser_version_error(parser)
        if parser_error:
            result["errors"].append(parser_error)
    if result["errors"]:
        return result

    workflow, error = _workflow_run(repo, run_id)
    if workflow is None:
        result["errors"].append(error or "workflow run could not be resolved")
        return result
    result["workflow"] = {
        "id": workflow.get("id"),
        "name": workflow.get("name"),
        "path": workflow.get("path"),
        "event": workflow.get("event"),
        "head_sha": workflow.get("head_sha"),
        "status": workflow.get("status"),
        "conclusion": workflow.get("conclusion"),
        "created_at": workflow.get("created_at"),
        "updated_at": workflow.get("updated_at"),
    }
    if workflow.get("head_sha") != candidate_sha:
        result["errors"].append(
            f"workflow run belongs to {workflow.get('head_sha')}, not exact candidate {candidate_sha}"
        )
    if workflow.get("status") != "completed":
        result["errors"].append(f"workflow run is not completed (status={workflow.get('status')})")
    if workflow.get("conclusion") != "success":
        result["errors"].append(f"workflow run conclusion is not success ({workflow.get('conclusion')})")
    if result["errors"]:
        return result

    artifacts, error = _artifacts_for_run(repo, run_id)
    if artifacts is None:
        result["errors"].append(error or "artifact listing could not be resolved")
        return result
    artifact = next(
        (
            item
            for item in artifacts
            if item.get("id") == artifact_id and item.get("name") == artifact_name
        ),
        None,
    )
    if artifact is None:
        result["errors"].append(
            f"artifact id/name pair not found on workflow run: id={artifact_id} name={artifact_name!r}"
        )
        return result
    if artifact.get("expired") is True:
        result["errors"].append("referenced artifact is expired")
        return result

    with tempfile.TemporaryDirectory(prefix="onecompany-evidence-") as tmp:
        root = Path(tmp)
        download_error = _download_artifact(repo, run_id, artifact_name, root)
        if download_error:
            result["errors"].append(download_error)
            return result
        digest, files, digest_error = _artifact_digest(root)
        if digest_error:
            result["errors"].append(digest_error)
            return result
        extracted, parse_error = parse_report(root, parser, candidate_sha, base_sha)
        if extracted is None:
            result["errors"].append(parse_error or "artifact parser returned no evidence")
            return result

    result["artifact"] = {
        "id": artifact.get("id"),
        "name": artifact.get("name"),
        "size_in_bytes": artifact.get("size_in_bytes"),
        "created_at": artifact.get("created_at"),
        "updated_at": artifact.get("updated_at"),
        "expires_at": artifact.get("expires_at"),
        "digest_sha256": digest,
        "files": files,
    }
    result["parser"] = {
        "kind": parser.get("kind"),
        "version": parser.get("version", 1),
        "path": parser.get("path"),
        "family": parser.get("family"),
    }
    result["extracted"] = extracted
    result["verified"] = True
    return result


def verify_review_reference(repo: str, pr: int, candidate_sha: str, reference: dict[str, Any]) -> dict[str, Any]:
    """Verify exact-commit GitHub review evidence.

    KERNEL-003 verifies platform provenance and exact commit identity. Mapping that
    platform principal into CompanyOS authorization is intentionally owned by
    KERNEL-004; therefore this function records reviewer_login but does not infer
    human-owner or other privileges from a packet actor string.
    """
    result: dict[str, Any] = {
        "verified": False,
        "review_id": reference.get("review_id"),
        "candidate_sha": candidate_sha,
        "errors": [],
    }
    review_id = reference.get("review_id")
    if not isinstance(review_id, int) or isinstance(review_id, bool) or review_id <= 0:
        result["errors"].append("review_id must be a positive integer")
        return result
    review, error = _review(repo, pr, review_id)
    if review is None:
        result["errors"].append(error or "review could not be resolved")
        return result
    state = str(review.get("state") or "").upper()
    commit_id = review.get("commit_id")
    login = ((review.get("user") or {}).get("login"))
    result.update(
        {
            "state": state,
            "commit_id": commit_id,
            "reviewer_login": login,
            "submitted_at": review.get("submitted_at"),
        }
    )
    if commit_id != candidate_sha:
        result["errors"].append("review does not target exact candidate SHA")
    if state != "APPROVED":
        result["errors"].append(f"review is not an APPROVED platform review (state={state or '<missing>'})")
    if not isinstance(login, str) or not login:
        result["errors"].append("review has no platform reviewer identity")
    result["verified"] = not result["errors"]
    return result


def aggregate_extracted(verified: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, str], list[str]]:
    coverage: dict[str, float] = {}
    families: dict[str, str] = {}
    errors: list[str] = []
    for item in verified:
        if not item.get("verified"):
            errors.append(f"evidence {item.get('id')} is not verified")
            continue
        extracted = item.get("extracted") or {}
        for metric, value in (extracted.get("coverage") or {}).items():
            try:
                normalized = _percent(value, f"coverage.{metric}")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if metric in coverage and coverage[metric] != normalized:
                errors.append(
                    f"conflicting extracted coverage values for {metric}: "
                    f"{coverage[metric]} vs {normalized}"
                )
            else:
                coverage[str(metric)] = normalized
        for family, status in (extracted.get("test_families") or {}).items():
            normalized = str(status).lower()
            current = families.get(str(family))
            if current == "fail" or normalized == "fail":
                families[str(family)] = "fail"
            elif current is None:
                families[str(family)] = normalized
            elif current != normalized:
                families[str(family)] = "fail"
    return coverage, families, errors


def evaluate_quality(
    quality: dict[str, Any],
    profile_name: str,
    risk_level: str,
    code_change: bool,
    coverage: dict[str, float],
    families: dict[str, str],
) -> list[str]:
    """Evaluate only extracted platform-backed facts against versioned policy."""
    errors: list[str] = []
    profile = quality.get("profiles", {}).get(profile_name)
    if not isinstance(profile, dict):
        return [f"unknown quality profile {profile_name!r}"]
    if code_change:
        metrics = {
            "line": "line_coverage_min",
            "branch": "branch_coverage_min",
            "changed_line": "changed_line_coverage_min",
            "mutation": "mutation_score_min",
        }
        for metric, threshold_key in metrics.items():
            threshold = profile.get(threshold_key)
            value = coverage.get(metric)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"verified evidence missing required {metric} metric")
                continue
            try:
                value = _percent(value, f"verified {metric}")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and value < threshold:
                errors.append(f"verified {metric}={value} is below {profile_name} threshold {threshold}")
    required_families = quality.get("risk_required_families", {}).get(risk_level, [])
    for family in required_families:
        if families.get(str(family)) != "pass":
            errors.append(f"verified evidence does not prove PASS for required test family {family}")
    return errors


def build_attestation(
    *,
    repo: str,
    work_unit: str,
    pr: int,
    candidate_sha: str,
    base_sha: str,
    profile: str,
    risk_level: str,
    material_authors: list[str],
    artifacts: list[dict[str, Any]],
    review: dict[str, Any],
    coverage: dict[str, float],
    test_families: dict[str, str],
    policy_revision: str,
    verdict: str,
) -> dict[str, Any]:
    return {
        "schema": "onecompany-assurance-attestation-v1",
        "repository": repo,
        "work_unit": work_unit,
        "pr": pr,
        "head_sha": candidate_sha,
        "base_sha": base_sha,
        "quality_profile": profile,
        "risk_level": risk_level,
        "material_authors": sorted(set(material_authors)),
        "review": review,
        "artifacts": [
            {
                "evidence_id": item.get("id"),
                "workflow_run_id": (item.get("workflow") or {}).get("id"),
                "artifact_id": (item.get("artifact") or {}).get("id"),
                "artifact_name": (item.get("artifact") or {}).get("name"),
                "digest_sha256": (item.get("artifact") or {}).get("digest_sha256"),
                "parser": item.get("parser"),
            }
            for item in artifacts
        ],
        "extracted": {"coverage": coverage, "test_families": test_families},
        "policy_revision": policy_revision,
        "verdict": verdict,
    }


def verify_packet_evidence(
    packet: dict[str, Any],
    *,
    repo: str,
    pr: int,
    base_sha: str,
    policy_revision: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    candidate_sha = packet.get("candidate_sha")
    if not isinstance(candidate_sha, str) or len(candidate_sha) != 40:
        return None, ["candidate_sha must be present before platform evidence verification"]
    context, error = verify_pr_context(repo, pr, candidate_sha, base_sha)
    if context is None:
        return None, [error or "live PR context could not be verified"]

    evidence = packet.get("evidence") or {}
    references = evidence.get("references") if isinstance(evidence, dict) else None
    if not isinstance(references, list) or not references:
        return None, ["merge-grade packet requires evidence.references with platform-verifiable artifacts"]

    verified: list[dict[str, Any]] = []
    errors: list[str] = []
    for reference in references:
        if not isinstance(reference, dict):
            errors.append("evidence reference must be an object")
            continue
        result = verify_artifact_reference(repo, candidate_sha, base_sha, reference)
        verified.append(result)
        errors.extend(str(value) for value in result.get("errors", []))

    coverage, families, aggregation_errors = aggregate_extracted(verified)
    errors.extend(aggregation_errors)
    quality = load_json(CONTROL / "quality.json")
    profile = str(packet.get("quality_profile") or quality.get("profile") or "")
    errors.extend(
        evaluate_quality(
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
        review = verify_review_reference(repo, pr, candidate_sha, review_ref)
        errors.extend(str(value) for value in review.get("errors", []))

    verdict = "PASS" if not errors else "UNVERIFIED"
    attestation = build_attestation(
        repo=repo,
        work_unit=str(packet.get("work_unit") or ""),
        pr=pr,
        candidate_sha=candidate_sha,
        base_sha=base_sha,
        profile=profile,
        risk_level=str(packet.get("risk_level") or "low"),
        material_authors=[str(value) for value in packet.get("material_authors", []) if value],
        artifacts=verified,
        review=review,
        coverage=coverage,
        test_families=families,
        policy_revision=policy_revision,
        verdict=verdict,
    )
    return attestation, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify artifact-backed engineering evidence")
    parser.add_argument("packet", type=Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--policy-revision", required=True)
    args = parser.parse_args()
    packet = json.loads(args.packet.read_text(encoding="utf-8"))
    attestation, errors = verify_packet_evidence(
        packet,
        repo=args.repo,
        pr=args.pr,
        base_sha=args.base_sha,
        policy_revision=args.policy_revision,
    )
    print(json.dumps({"attestation": attestation, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
