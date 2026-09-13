#!/usr/bin/env python3
"""Authoritative engineering assurance gate for OneCompany Work Units.

Packet validation proves requirements/risk/traceability structure. For
``merge_ready`` and ``done`` it is intentionally insufficient: merge-grade
quality and review truth must come from ``trusted_assurance`` using live GitHub
state, base-trusted policy, exact-SHA required checks, and downloaded artifacts.
Legacy packet-authored coverage/PASS/review fields are compatibility metadata;
they are neutralized before structural validation and can neither grant nor
deny merge-grade assurance.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

from assurance import CONTROL, load, policy_errors, validate_packet
from trusted_assurance import verify_trusted_packet

MERGE_STATUSES = {"merge_ready", "done"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
LEGACY_GATES = {
    "requirements",
    "risk",
    "architecture",
    "code_quality",
    "functional_qa",
    "nonfunctional_qa",
    "documentation",
    "independent_review",
}


def _platform_reference_errors(packet: dict) -> list[str]:
    """Validate the shape of candidate-nominated evidence references only."""
    if packet.get("status") not in MERGE_STATUSES:
        return []
    errors: list[str] = []
    evidence = packet.get("evidence") if isinstance(packet.get("evidence"), dict) else {}
    references = evidence.get("references")
    if not isinstance(references, list) or not references:
        errors.append("merge_ready/done requires evidence.references with platform evidence references")
        references = []
    seen: set[str] = set()
    for index, reference in enumerate(references):
        if not isinstance(reference, dict):
            errors.append(f"evidence.references[{index}] must be an object")
            continue
        evidence_id = reference.get("id")
        if not isinstance(evidence_id, str) or not evidence_id:
            errors.append(f"evidence.references[{index}] requires stable id")
        elif evidence_id in seen:
            errors.append(f"duplicate platform evidence reference id: {evidence_id}")
        else:
            seen.add(evidence_id)
        if reference.get("provider") != "github_actions":
            errors.append(f"evidence reference {evidence_id or index} must use provider=github_actions")
        if reference.get("source_kind") != "artifact":
            errors.append(f"evidence reference {evidence_id or index} must use source_kind=artifact")
        if not isinstance(reference.get("workflow_run_id"), int) or reference.get("workflow_run_id", 0) <= 0:
            errors.append(f"evidence reference {evidence_id or index} requires positive workflow_run_id")
        if not isinstance(reference.get("artifact_id"), int) or reference.get("artifact_id", 0) <= 0:
            errors.append(f"evidence reference {evidence_id or index} requires positive artifact_id")
        if not reference.get("artifact_name"):
            errors.append(f"evidence reference {evidence_id or index} requires artifact_name")
        parser = reference.get("parser")
        if not isinstance(parser, dict) or not parser.get("kind") or not parser.get("path"):
            errors.append(f"evidence reference {evidence_id or index} requires parser.kind and parser.path")

    review_ref = evidence.get("review_reference")
    if not isinstance(review_ref, dict) or not isinstance(review_ref.get("review_id"), int) or review_ref.get("review_id", 0) <= 0:
        errors.append("merge_ready/done requires evidence.review_reference.review_id")
    return errors


def _structural_view(packet: dict) -> dict:
    """Return a copy suitable for structural validation without trusting claims.

    ``assurance.validate_packet`` predates artifact-backed evidence and checks
    packet-authored coverage/test/review values. We preserve all of its valuable
    requirements/risk/traceability invariants while replacing those legacy
    merge-grade claims with neutral compatibility placeholders. The real quality
    decision is performed afterwards by ``verify_trusted_packet``.
    """
    view = copy.deepcopy(packet)
    if view.get("status") not in MERGE_STATUSES:
        return view

    evidence = view.setdefault("evidence", {})
    candidate_sha = view.get("candidate_sha")
    quality = load(CONTROL / "quality.json")
    profile_name = view.get("quality_profile") or quality.get("profile")
    profile = quality.get("profiles", {}).get(profile_name, {})

    # Stable evidence IDs for traceability come from the platform references.
    references = evidence.get("references") if isinstance(evidence.get("references"), list) else []
    reference_ids = [str(item.get("id")) for item in references if isinstance(item, dict) and item.get("id")]
    if reference_ids:
        evidence["artifacts"] = [
            {"id": evidence_id, "kind": "platform-reference", "reference": f"platform://{evidence_id}"}
            for evidence_id in reference_ids
        ]

    # These values exist only to keep the legacy structural validator from making
    # a second quality decision. They are never returned as evidence and never
    # influence trusted_assurance's verdict.
    evidence["coverage"] = {
        "line": profile.get("line_coverage_min", 0),
        "branch": profile.get("branch_coverage_min", 0),
        "changed_line": profile.get("changed_line_coverage_min", 0),
        "mutation": profile.get("mutation_score_min", 0),
    }
    planned = view.get("test_plan", {}).get("families", [])
    evidence["test_family_results"] = {str(family): "pass" for family in planned}
    evidence["gates"] = {name: "pass" for name in LEGACY_GATES}
    authors = {str(value) for value in view.get("material_authors", []) if value}
    placeholder = "platform-review-placeholder"
    while placeholder in authors:
        placeholder += "-independent"
    evidence["independent_review"] = {
        "actor": placeholder,
        "sha": candidate_sha,
        "verdict": "pass",
    }
    if isinstance(candidate_sha, str) and SHA40.fullmatch(candidate_sha):
        evidence["sha"] = candidate_sha
    return view


def validate_structure(packet: dict) -> tuple[list[str], list[str]]:
    errors, warnings = validate_packet(_structural_view(packet))
    errors.extend(_platform_reference_errors(packet))
    # De-duplicate while preserving deterministic order.
    errors = list(dict.fromkeys(errors))
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="OneCompany authoritative engineering assurance gate")
    parser.add_argument("packet", type=Path)
    parser.add_argument("--repo", help="owner/repo; required for merge_ready/done")
    parser.add_argument("--pr", type=int, help="pull request number; required for merge_ready/done")
    parser.add_argument("--base-sha", help="reviewed base SHA; required for merge_ready/done")
    args = parser.parse_args()

    p_errors = policy_errors()
    if p_errors:
        for error in p_errors:
            print(f"ERROR: {error}")
        return 1

    packet = load(args.packet)
    errors, warnings = validate_structure(packet)
    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Assurance gate FAILED ({len(errors)} structural/reference error(s), {len(warnings)} warning(s)).")
        return 1

    if packet.get("status") not in MERGE_STATUSES:
        print(f"Assurance structure PASS ({len(warnings)} warning(s)); platform attestation is not required before merge-ready.")
        return 0

    if not args.repo or not args.pr or not args.base_sha:
        print("ERROR: merge_ready/done assurance requires --repo, --pr and --base-sha for platform verification")
        return 1
    if not SHA40.fullmatch(args.base_sha):
        print("ERROR: --base-sha must be a lowercase 40-hex commit SHA")
        return 1

    attestation, evidence_errors = verify_trusted_packet(
        packet,
        repo=args.repo,
        pr=args.pr,
        base_sha=args.base_sha,
    )
    if evidence_errors or not attestation or attestation.get("verdict") != "PASS":
        for error in evidence_errors:
            print(f"ERROR: {error}")
        print(json.dumps({"attestation": attestation}, indent=2))
        print("Assurance gate UNVERIFIED: packet claims cannot substitute for platform-backed evidence.")
        return 1

    print(json.dumps({"attestation": attestation}, indent=2))
    print("Assurance gate PASS: structure and base-trusted platform evidence verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
