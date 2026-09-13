#!/usr/bin/env python3
"""Policy-correct OneCompany engineering assurance validator.

The historical validator is retained in ``assurance_legacy`` so this layer can
apply lifecycle and traceability-policy semantics explicitly while preserving
all established validation behavior. Merge authority still comes from
``trusted_assurance``; packet-authored quality/review claims are compatibility
metadata only at the authoritative gate.
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path

import assurance_legacy as _legacy

ROOT = _legacy.ROOT
CONTROL = _legacy.CONTROL
POLICY_FILES = _legacy.POLICY_FILES
REQUIRED_PACKET = _legacy.REQUIRED_PACKET
MERGE_STATUSES = {"merge_ready", "done"}
ASSURED_STATUSES = {"ready", "review", "in_progress", "merge_ready", "done"}
SHA40 = _legacy.SHA40
PROFILE_ORDER = _legacy.PROFILE_ORDER
TYPE_PREFIX = _legacy.TYPE_PREFIX

load = _legacy.load
validate_waivers = _legacy.validate_waivers
unique_ids = _legacy.unique_ids
print_matrix = _legacy.print_matrix
print_risks = _legacy.print_risks
evidence_manifest = _legacy.evidence_manifest

_EXTERNAL_TRACE_PREFIXES = ("DEFECT-", "REGRESSION-", "FITNESS-", "QFF-")
_UNKNOWN_COVER_RE = re.compile(r"^(?P<test>[^:]+): covers unknown trace target (?P<target>.+)$")
_MITIGATION_TEST_RE = re.compile(r"^mitigation (?P<mitigation>\S+) lacks verification test trace$")


def policy_errors() -> list[str]:
    """Validate baseline policy plus the lifecycle semantics enforced here."""
    errors = list(_legacy.policy_errors())
    trace = load(CONTROL / "traceability.json")
    orphan_policy = trace.get("orphan_policy", {})
    if orphan_policy.get("untested_high_or_critical_risk_mitigation_blocks_merge") is not True:
        errors.append("traceability policy must explicitly require untested high/critical mitigations to block merge")
    return errors


def _external_trace_target_allowed(test: dict, target: str) -> bool:
    if any(target.startswith(prefix) and len(target) > len(prefix) for prefix in _EXTERNAL_TRACE_PREFIXES):
        return True
    return target == "EXPLORATORY" and test.get("exploratory") is True


def _mitigations_that_must_be_tested_at_merge(packet: dict) -> set[str]:
    """Return mitigation IDs whose risk is high/critical before mitigation.

    A mitigation controls the inherent risk, so classification uses the
    inherent score. Low/medium mitigations may be planned earlier, but the
    repository policy makes only high/critical untested mitigations a merge
    blocker.
    """
    if packet.get("status") not in MERGE_STATUSES:
        return set()
    trace = load(CONTROL / "traceability.json")
    if trace.get("orphan_policy", {}).get("untested_high_or_critical_risk_mitigation_blocks_merge") is not True:
        return set()
    risk_policy = load(CONTROL / "risk.json")
    high_min = risk_policy.get("bands", {}).get("high", {}).get("min", 10)
    required: set[str] = set()
    for risk in packet.get("risks", []):
        if not isinstance(risk, dict):
            continue
        score = risk.get("inherent_score")
        if not isinstance(score, (int, float)) or score < high_min:
            continue
        for mitigation in risk.get("mitigations", []):
            if isinstance(mitigation, dict) and mitigation.get("id"):
                required.add(str(mitigation["id"]))
    return required


def validate_packet(packet: dict) -> tuple[list[str], list[str]]:
    """Validate a packet using the repository's declared lifecycle policy.

    ``review`` remains a supported assured lifecycle state. It has the same
    structural completeness expectations as ``ready`` but is not a merge
    state. Low/medium mitigations do not become verification blockers until
    policy says they should; high/critical mitigations must be test-traced at
    merge. Regression-defect and fitness-function targets are valid external
    trace targets, and exploratory tests can explicitly use ``EXPLORATORY``.
    """
    if not isinstance(packet, dict):
        return ["packet must be an object"], []

    original_status = packet.get("status")
    normalized = copy.deepcopy(packet)
    if original_status == "review":
        normalized["status"] = "ready"

    errors, warnings = _legacy.validate_packet(normalized)

    required_mitigation_tests = _mitigations_that_must_be_tested_at_merge(packet)
    tests_by_id = {
        str(test.get("id")): test
        for test in packet.get("test_plan", {}).get("tests", [])
        if isinstance(test, dict) and test.get("id")
    }
    filtered: list[str] = []
    for error in errors:
        mitigation_match = _MITIGATION_TEST_RE.match(error)
        if mitigation_match:
            mitigation_id = mitigation_match.group("mitigation")
            if mitigation_id not in required_mitigation_tests:
                continue

        cover_match = _UNKNOWN_COVER_RE.match(error)
        if cover_match:
            test = tests_by_id.get(cover_match.group("test"), {})
            if _external_trace_target_allowed(test, cover_match.group("target")):
                continue

        filtered.append(error)
    errors = filtered

    if original_status not in {"draft", *ASSURED_STATUSES}:
        # Legacy validation already emits a status error for every unsupported
        # state. This branch only gives the current complete lifecycle list.
        errors = [error for error in errors if not error.startswith("status must be ")]
        errors.append("status must be draft|ready|review|in_progress|merge_ready|done")

    if original_status in MERGE_STATUSES:
        authors = packet.get("material_authors")
        if not isinstance(authors, list) or not authors or any(not isinstance(author, str) or not author.strip() for author in authors):
            errors.append("merge_ready/done packet requires a complete non-empty material_authors snapshot")

    # Keep deterministic diagnostics if a compatibility path produced the same
    # message twice.
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="OneCompany engineering assurance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("policy")
    for name in ("validate", "trace", "risk", "evidence"):
        command = sub.add_parser(name)
        command.add_argument("packet", type=Path)
    args = parser.parse_args()

    p_errors = policy_errors()
    if p_errors:
        for error in p_errors:
            print(f"ERROR: {error}")
        return 1
    if args.command == "policy":
        print("OneCompany assurance policy PASS.")
        return 0

    packet = load(args.packet)
    errors, warnings = validate_packet(packet)
    for warning in warnings:
        print(f"WARN: {warning}")
    if args.command == "validate":
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            print(f"Assurance FAILED ({len(errors)} error(s), {len(warnings)} warning(s)).")
            return 1
        print(f"Assurance PASS ({len(warnings)} warning(s)).")
        return 0
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    if args.command == "trace":
        print_matrix(packet)
    elif args.command == "risk":
        print_risks(packet)
    elif args.command == "evidence":
        import json
        print(json.dumps(evidence_manifest(packet), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
