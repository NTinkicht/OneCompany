#!/usr/bin/env python3
"""Engineering assurance structure gate with optional trusted attestation.

Offline packet validation proves requirements/risk/traceability structure only.
For ``merge_ready`` and ``done``, merge-grade quality and review truth is provided
only when live GitHub context is supplied, or directly through ``onecompany.py
attest``. Legacy packet-authored coverage/PASS/review fields are compatibility
metadata; they are neutralized before structural validation and can neither grant
nor deny trusted merge-grade assurance.
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
    """Neutralize legacy evidence claims while preserving structural invariants."""
    view = copy.deepcopy(packet)
    if view.get("status") not in MERGE_STATUSES:
        return view

    evidence = view.setdefault("evidence", {})
    candidate_sha = view.get("candidate_sha")
    quality = load(CONTROL / "quality.json")
    profile_name = view.get("quality_profile") or quality.get("profile")
    profile = quality.get("profiles", {}).get(profile_name, {})

    references = evidence.get("references") if isinstance(evidence.get("references"), list) else []
    reference_ids = [str(item.get("id")) for item in references if isinstance(item, dict) and item.get("id")]
    if reference_ids:
        evidence["artifacts"] = [
            {"id": evidence_id, "kind": "platform-reference", "reference": f"platform://{evidence_id}"}
            for evidence_id in reference_ids
        ]

    # Compatibility placeholders only. trusted_assurance never consumes them.
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
    evidence["independent_review"] = {"actor": placeholder, "sha": candidate_sha, "verdict": "pass"}
    if isinstance(candidate_sha, str) and SHA40.fullmatch(candidate_sha):
        evidence["sha"] = candidate_sha
    return view


def validate_structure(packet: dict) -> tuple[list[str], list[str]]:
    errors, warnings = validate_packet(_structural_view(packet))
    errors.extend(_platform_reference_errors(packet))
    return list(dict.fromkeys(errors)), warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="OneCompany assurance structure validation with optional trusted attestation")
    parser.add_argument("packet", type=Path)
    parser.add_argument("--repo", help="owner/repo for live platform attestation")
    parser.add_argument("--pr", type=int, help="pull request number for live platform attestation")
    parser.add_argument("--base-sha", help="reviewed base SHA for live platform attestation")
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
        print(f"Assurance structure FAILED ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1

    merge_grade = packet.get("status") in MERGE_STATUSES
    supplied = [args.repo is not None, args.pr is not None, args.base_sha is not None]
    if any(supplied) and not all(supplied):
        print("ERROR: live attestation requires --repo, --pr and --base-sha together")
        return 1

    if not all(supplied):
        suffix = " This is NOT merge evidence; run `python onecompany.py attest ...` with exact PR/base context." if merge_grade else ""
        print(f"Assurance structure PASS ({len(warnings)} warning(s)).{suffix}")
        return 0

    if not isinstance(args.base_sha, str) or not SHA40.fullmatch(args.base_sha):
        print("ERROR: --base-sha must be a lowercase 40-hex commit SHA")
        return 1

    attestation, evidence_errors = verify_trusted_packet(packet, repo=args.repo, pr=args.pr, base_sha=args.base_sha)
    if evidence_errors or not attestation or attestation.get("verdict") != "PASS":
        for error in evidence_errors:
            print(f"ERROR: {error}")
        print(json.dumps({"attestation": attestation}, indent=2))
        print("Assurance UNVERIFIED: packet claims cannot substitute for platform-backed evidence.")
        return 1

    print(json.dumps({"attestation": attestation}, indent=2))
    print("Assurance PASS: structure and base-trusted platform evidence verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
