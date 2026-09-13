#!/usr/bin/env python3
"""Authoritative merge/readiness assurance gate for OneCompany Work Unit packets."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from assurance import CONTROL, load, policy_errors, validate_packet


def hardening_errors(packet: dict) -> list[str]:
    errors: list[str] = []
    quality = load(CONTROL / "quality.json")
    risk_level = packet.get("risk_level", "low")
    status = packet.get("status")
    reqs = packet.get("requirements", [])
    risks = packet.get("risks", [])
    tests = packet.get("test_plan", {}).get("tests", [])
    links = packet.get("traceability", [])
    link_set = {(str(x.get("source")), str(x.get("target")), str(x.get("relationship"))) for x in links}

    # Requirement baseline quality beyond syntax: active WUs use approved-or-later requirements,
    # each requirement belongs to an objective, and risk/design trace is explicit where material.
    active_statuses = {"ready", "in_progress", "review", "merge_ready", "done"}
    if status in active_statuses:
        for req in reqs:
            rid = req.get("id", "<unknown>")
            if req.get("status") not in {"approved", "implemented", "verified"}:
                errors.append(f"{rid}: active Work Unit requires approved-or-later requirement status")
            statement = f" {str(req.get('statement', '')).lower()} "
            if statement.count(" shall ") != 1:
                errors.append(f"{rid}: requirement must contain exactly one normative 'shall' obligation")
            if not any(target == rid and rel == "objective_to_requirement" for _, target, rel in link_set):
                errors.append(f"traceability missing objective_to_requirement for {rid}")
            for risk_id in req.get("risk_ids", []):
                if (rid, risk_id, "requirement_to_risk") not in link_set:
                    errors.append(f"traceability missing {rid} -> risk {risk_id}")
            if risk_level in {"high", "critical"} and not any(source == rid and rel == "requirement_to_design_or_architecture" for source, _, rel in link_set):
                errors.append(f"{risk_level}-risk traceability missing design/architecture link for {rid}")

    # Risk acceptance cannot be an autonomous silent downgrade.
    for risk in risks:
        rid = risk.get("id", "<unknown>")
        residual = risk.get("residual_score", 0)
        acceptance = risk.get("acceptance")
        if risk.get("treatment") == "accept" and residual >= 10:
            if not isinstance(acceptance, dict) or not acceptance.get("approved_by"):
                errors.append(f"{rid}: accepting high/critical residual risk requires explicit acceptance authority")
        if residual >= 17:
            if not isinstance(acceptance, dict) or acceptance.get("human") is not True:
                errors.append(f"{rid}: critical residual risk acceptance must be human")

    if status not in {"merge_ready", "done"}:
        return errors

    evidence = packet.get("evidence", {})
    sha = evidence.get("sha")
    candidate_sha = packet.get("candidate_sha")
    if not isinstance(candidate_sha, str) or re.fullmatch(r"[0-9a-fA-F]{40}", candidate_sha) is None:
        errors.append("merge_ready/done packet requires a 40-hex candidate_sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-fA-F]{40}", sha) is None:
        errors.append("merge_ready/done evidence requires a 40-hex sha")
    if candidate_sha and sha != candidate_sha:
        errors.append("quantitative evidence is stale: evidence.sha != candidate_sha")

    # Quantitative quality is enforced, not merely reported.
    code_change = packet.get("code_change", True)
    profile_name = packet.get("quality_profile") or quality.get("profile")
    profile = quality.get("profiles", {}).get(profile_name)
    if profile is None:
        errors.append(f"unknown quality_profile {profile_name!r}")
    elif code_change:
        coverage = evidence.get("coverage", {})
        metrics = {
            "line": "line_coverage_min",
            "branch": "branch_coverage_min",
            "changed_line": "changed_line_coverage_min",
            "mutation": "mutation_score_min",
        }
        for metric, threshold_key in metrics.items():
            minimum = profile.get(threshold_key, 0)
            value = coverage.get(metric)
            if not isinstance(value, (int, float)):
                errors.append(f"coverage.{metric} is required for code-changing {profile_name} merge evidence")
            elif value < minimum:
                errors.append(f"coverage.{metric}={value} is below {profile_name} minimum {minimum}")

    # Every risk-required test family must have exact-candidate passing evidence.
    required_families = set(quality.get("risk_required_families", {}).get(risk_level, []))
    family_results = evidence.get("test_family_results", {})
    for family in sorted(required_families):
        if family_results.get(family) != "pass":
            errors.append(f"required test family {family} lacks PASS evidence")

    # Planned tests need evidence links at merge time; otherwise the matrix stops before proof.
    for test in tests:
        tid = test.get("id")
        if tid and not any(source == tid and rel == "test_to_evidence" for source, _, rel in link_set):
            errors.append(f"traceability missing test_to_evidence for {tid}")

    review = evidence.get("independent_review", {})
    if not isinstance(review, dict):
        errors.append("independent_review evidence object is required")
    else:
        if review.get("verdict") != "pass":
            errors.append("independent_review.verdict must be pass")
        if review.get("sha") != candidate_sha:
            errors.append("independent review must target exact candidate_sha")
        reviewer = review.get("actor")
        authors = set(packet.get("material_authors", []))
        if not reviewer:
            errors.append("independent review must name reviewer actor")
        elif reviewer in authors:
            errors.append("independent reviewer cannot be a material author")

    return errors


def validate(packet: dict) -> tuple[list[str], list[str]]:
    errors, warnings = validate_packet(packet)
    errors.extend(hardening_errors(packet))
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="OneCompany authoritative engineering assurance gate")
    parser.add_argument("packet", type=Path)
    args = parser.parse_args()
    p_errors = policy_errors()
    if p_errors:
        for error in p_errors:
            print(f"ERROR: {error}")
        return 1
    packet = load(args.packet)
    errors, warnings = validate(packet)
    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Assurance gate FAILED ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1
    print(f"Assurance gate PASS ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
