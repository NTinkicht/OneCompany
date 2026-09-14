#!/usr/bin/env python3
"""Dependency-free OneCompany engineering assurance validator and reporter."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTROL = ROOT / ".onecompany"

POLICY_FILES = ["quality.json", "requirements.json", "risk.json", "traceability.json", "architecture.json", "waivers.json", "quality-baseline.json"]
REQUIRED_PACKET = ["work_unit", "status", "objective", "risk_level", "requirements", "acceptance_criteria", "risks", "traceability", "test_plan", "documentation_impact", "architecture_impact", "release", "evidence"]
ASSURED_STATUSES = {"ready", "in_progress", "merge_ready", "done"}
MERGE_STATUSES = {"merge_ready", "done"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
PROFILE_ORDER = {"prototype": 0, "standard": 1, "production": 2, "high_assurance": 3, "regulated": 4}
TYPE_PREFIX = {"business": "BR", "user": "UR", "functional": "FR", "nonfunctional": "NFR", "security": "SEC", "data": "DATA", "operations": "OPS", "ux": "UX", "constraint": "CON"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def policy_errors() -> list[str]:
    errors: list[str] = []
    for name in POLICY_FILES:
        path = CONTROL / name
        if not path.exists():
            errors.append(f"missing policy: {path}")
            continue
        try:
            load(path)
        except Exception as exc:
            errors.append(f"invalid JSON in {name}: {exc}")
    if errors:
        return errors
    quality = load(CONTROL / "quality.json")
    if quality.get("profile") not in quality.get("profiles", {}):
        errors.append("quality.profile must name a configured profile")
    if not quality.get("principles", {}).get("exact_head_evidence_required"):
        errors.append("exact-head evidence must remain required")
    risk = load(CONTROL / "risk.json")
    bands = risk.get("bands", {})
    expected = {"low": (1, 4), "medium": (5, 9), "high": (10, 16), "critical": (17, 25)}
    for name, (low, high) in expected.items():
        if bands.get(name, {}).get("min") != low or bands.get(name, {}).get("max") != high:
            errors.append(f"risk band {name} differs from reference scale")
    trace = load(CONTROL / "traceability.json")
    if not trace.get("bidirectional"):
        errors.append("traceability must remain bidirectional")
    errors.extend(validate_waivers(load(CONTROL / "waivers.json")))
    return errors


def validate_waivers(doc: dict) -> list[str]:
    errors: list[str] = []
    today = date.today()
    for item in doc.get("waivers", []):
        wid = item.get("id", "<unnamed>")
        for field in ("rule", "reason", "owner", "issue", "expires", "risk", "compensating_control"):
            if not item.get(field):
                errors.append(f"waiver {wid}: missing {field}")
        expiry = item.get("expires")
        if expiry:
            try:
                if date.fromisoformat(expiry) < today:
                    errors.append(f"waiver {wid}: expired on {expiry}")
            except ValueError:
                errors.append(f"waiver {wid}: expires must be YYYY-MM-DD")
    return errors


def validate_packet(packet: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in REQUIRED_PACKET:
        if field not in packet:
            errors.append(f"packet missing {field}")
    if errors:
        return errors, warnings

    status = packet.get("status")
    if status not in {"draft", "ready", "in_progress", "merge_ready", "done"}:
        errors.append("status must be draft|ready|in_progress|merge_ready|done")
    risk_level = packet.get("risk_level")
    if risk_level not in {"low", "medium", "high", "critical"}:
        errors.append("risk_level must be low|medium|high|critical")
        risk_level = "low"

    req_policy = load(CONTROL / "requirements.json")
    quality = load(CONTROL / "quality.json")
    risk_policy = load(CONTROL / "risk.json")
    trace_policy = load(CONTROL / "traceability.json")

    reqs = packet.get("requirements", [])
    acs = packet.get("acceptance_criteria", [])
    risks = packet.get("risks", [])
    links = packet.get("traceability", [])
    tests = packet.get("test_plan", {}).get("tests", [])

    if not isinstance(reqs, list):
        errors.append("requirements must be an array")
        reqs = []
    if not isinstance(acs, list):
        errors.append("acceptance_criteria must be an array")
        acs = []
    if not isinstance(risks, list):
        errors.append("risks must be an array")
        risks = []
    if not isinstance(links, list):
        errors.append("traceability must be an array")
        links = []
    if not isinstance(tests, list):
        errors.append("test_plan.tests must be an array")
        tests = []

    if status in ASSURED_STATUSES:
        if not reqs:
            errors.append("requirements must contain at least one requirement at ready or later")
        if not acs:
            errors.append("acceptance_criteria must contain at least one acceptance criterion at ready or later")
        if not tests:
            errors.append(f"{status} packet requires at least one planned test")

    req_ids = unique_ids(reqs, "requirement", errors)
    ac_ids = unique_ids(acs, "acceptance criterion", errors)
    risk_ids = unique_ids(risks, "risk", errors)
    test_ids = unique_ids(tests, "test", errors)

    avoid = [word.lower() for word in req_policy.get("language_rules", {}).get("avoid", [])]
    mandatory = req_policy.get("mandatory_attributes", [])
    for req in reqs:
        rid = req.get("id", "<unknown>")
        for field in mandatory:
            if field not in req or req.get(field) in (None, "", []):
                if field == "risk_ids" and risk_level == "low":
                    continue
                errors.append(f"{rid}: requirement missing {field}")
        req_type = req.get("type")
        expected_prefix = TYPE_PREFIX.get(req_type)
        if expected_prefix and not str(rid).startswith(expected_prefix + "-"):
            errors.append(f"{rid}: id prefix does not match requirement type {req_type}")
        statement = str(req.get("statement", ""))
        shall_count = len(re.findall(r"\bshall\b", statement, flags=re.IGNORECASE))
        if shall_count == 0:
            errors.append(f"{rid}: formal requirement must use 'shall'")
        elif shall_count > 1:
            errors.append(f"{rid}: requirement must contain one obligation; found {shall_count} 'shall' clauses")
        lowered = statement.lower()
        for term in avoid:
            if term and term in lowered:
                errors.append(f"{rid}: ambiguous/discouraged term '{term}'")
        if status in ASSURED_STATUSES and req.get("status") not in {"approved", "implemented", "verified"}:
            errors.append(f"{rid}: ready-or-later packet requires approved requirement status")
        if status in MERGE_STATUSES and req.get("status") != "verified":
            errors.append(f"{rid}: merge_ready/done packet requires requirement status 'verified'")
        if req.get("type") == "nonfunctional":
            measure = req.get("nfr_measure")
            if not isinstance(measure, dict) or not all(measure.get(k) for k in ("metric", "target", "method", "conditions")):
                errors.append(f"{rid}: nonfunctional requirement needs measurable metric/target/method/conditions")
        for ac in req.get("acceptance_criteria", []):
            if ac not in ac_ids:
                errors.append(f"{rid}: references missing acceptance criterion {ac}")
        for risk_id in req.get("risk_ids", []):
            if risk_id not in risk_ids:
                errors.append(f"{rid}: references missing risk {risk_id}")

    for ac in acs:
        aid = ac.get("id", "<unknown>")
        if not ac.get("statement"):
            errors.append(f"{aid}: acceptance criterion missing statement")
        if not ac.get("verification_method"):
            errors.append(f"{aid}: acceptance criterion missing verification_method")

    domains = set(risk_policy.get("domains", []))
    mitigation_ids: set[str] = set()
    for risk in risks:
        rid = risk.get("id", "<unknown>")
        for field in risk_policy.get("mandatory_attributes", []):
            if field not in risk or risk.get(field) in (None, "", []):
                errors.append(f"{rid}: risk missing {field}")
        if risk.get("domain") not in domains:
            errors.append(f"{rid}: unknown risk domain {risk.get('domain')}")
        likelihood = risk.get("likelihood", 0)
        impact = risk.get("impact", 0)
        residual_likelihood = risk.get("residual_likelihood", 0)
        residual_impact = risk.get("residual_impact", 0)
        inherent = likelihood * impact if isinstance(likelihood, (int, float)) and isinstance(impact, (int, float)) else 0
        residual = residual_likelihood * residual_impact if isinstance(residual_likelihood, (int, float)) and isinstance(residual_impact, (int, float)) else 0
        if risk.get("inherent_score") != inherent:
            errors.append(f"{rid}: inherent_score must equal likelihood*impact ({inherent})")
        if risk.get("residual_score") != residual:
            errors.append(f"{rid}: residual_score must equal residual_likelihood*residual_impact ({residual})")
        if residual > inherent:
            errors.append(f"{rid}: residual risk cannot exceed inherent risk without explicit re-baselining")
        if residual >= 17:
            acceptance = risk.get("acceptance")
            if not isinstance(acceptance, dict) or not acceptance.get("human") or not acceptance.get("approved_by"):
                errors.append(f"{rid}: critical residual risk requires explicit human acceptance")
        if residual >= 10 and not risk.get("owner"):
            errors.append(f"{rid}: high residual risk requires owner")
        mitigations = risk.get("mitigations", [])
        if risk.get("treatment") == "reduce" and not mitigations:
            errors.append(f"{rid}: reduce treatment requires at least one mitigation")
        for mitigation in mitigations:
            if not isinstance(mitigation, dict):
                errors.append(f"{rid}: mitigation must be an object with stable id and description")
                continue
            mid = mitigation.get("id")
            if not mid:
                errors.append(f"{rid}: mitigation must have stable id")
                continue
            if mid in mitigation_ids:
                errors.append(f"duplicate mitigation id: {mid}")
            mitigation_ids.add(mid)
            if not mitigation.get("description"):
                errors.append(f"{rid}: mitigation {mid} missing description")

    evidence = packet.get("evidence", {})
    evidence_artifacts = evidence.get("artifacts", []) if isinstance(evidence, dict) else []
    evidence_ids = unique_ids(evidence_artifacts, "evidence artifact", errors) if evidence_artifacts else set()

    known_relationships = set(trace_policy.get("required_links", []))
    link_set: set[tuple[str, str, str]] = set()
    for item in links:
        if not isinstance(item, dict):
            errors.append("traceability entry must be an object")
            continue
        source = str(item.get("source") or "")
        target = str(item.get("target") or "")
        relationship = str(item.get("relationship") or "")
        if not source or not target or not relationship:
            errors.append("traceability entry requires source, target and relationship")
            continue
        if known_relationships and relationship not in known_relationships:
            errors.append(f"traceability has unknown relationship {relationship}")
        link_set.add((source, target, relationship))
        if relationship == "objective_to_requirement" and target not in req_ids:
            errors.append(f"traceability objective_to_requirement targets missing requirement {target}")
        elif relationship == "requirement_to_acceptance_criterion":
            if source not in req_ids:
                errors.append(f"traceability requirement_to_acceptance_criterion has missing requirement source {source}")
            if target not in ac_ids:
                errors.append(f"traceability requirement_to_acceptance_criterion targets missing AC {target}")
        elif relationship == "requirement_to_risk":
            if source not in req_ids:
                errors.append(f"traceability requirement_to_risk has missing requirement source {source}")
            if target not in risk_ids:
                errors.append(f"traceability requirement_to_risk targets missing risk {target}")
        elif relationship == "requirement_to_design_or_architecture" and source not in req_ids:
            errors.append(f"traceability requirement_to_design_or_architecture has missing requirement source {source}")
        elif relationship == "requirement_to_work_unit":
            if source not in req_ids:
                errors.append(f"traceability requirement_to_work_unit has missing requirement source {source}")
            if target != str(packet.get("work_unit")):
                errors.append(f"traceability requirement_to_work_unit must target {packet.get('work_unit')}, got {target}")
        elif relationship == "requirement_to_test":
            if source not in req_ids:
                errors.append(f"traceability requirement_to_test has missing requirement source {source}")
            if target not in test_ids:
                errors.append(f"traceability requirement_to_test targets missing test {target}")
        elif relationship == "risk_to_mitigation":
            if source not in risk_ids:
                errors.append(f"traceability risk_to_mitigation has missing risk source {source}")
            if target not in mitigation_ids:
                errors.append(f"traceability risk_to_mitigation targets missing mitigation {target}")
        elif relationship == "mitigation_to_test":
            if source not in mitigation_ids:
                errors.append(f"traceability mitigation_to_test has missing mitigation source {source}")
            if target not in test_ids:
                errors.append(f"traceability mitigation_to_test targets missing test {target}")
        elif relationship == "test_to_evidence":
            if source not in test_ids:
                errors.append(f"traceability test_to_evidence has missing test source {source}")
            if evidence_ids and target not in evidence_ids:
                errors.append(f"traceability test_to_evidence targets missing evidence artifact {target}")
        elif relationship == "change_to_requirement" and target not in req_ids:
            errors.append(f"traceability change_to_requirement targets missing requirement {target}")

    if status in ASSURED_STATUSES:
        for req in reqs:
            rid = req.get("id")
            if not any(target == rid and rel == "objective_to_requirement" for _, target, rel in link_set):
                errors.append(f"traceability missing objective_to_requirement for {rid}")
            for ac in req.get("acceptance_criteria", []):
                if (rid, ac, "requirement_to_acceptance_criterion") not in link_set:
                    errors.append(f"traceability missing {rid} -> {ac}")
            for risk_id in req.get("risk_ids", []):
                if (rid, risk_id, "requirement_to_risk") not in link_set:
                    errors.append(f"traceability missing {rid} -> risk {risk_id}")
            if not any(source == rid and rel == "requirement_to_design_or_architecture" for source, _, rel in link_set):
                errors.append(f"traceability missing requirement_to_design_or_architecture for {rid}")
            if (rid, str(packet.get("work_unit")), "requirement_to_work_unit") not in link_set:
                errors.append(f"traceability missing requirement_to_work_unit for {rid}")
            if not any(source == rid and target in test_ids and rel == "requirement_to_test" for source, target, rel in link_set):
                errors.append(f"traceability missing requirement_to_test for {rid}")

        for aid in ac_ids:
            if not any(target == aid and rel == "requirement_to_acceptance_criterion" for _, target, rel in link_set):
                errors.append(f"orphan acceptance criterion: {aid}")

        for risk in risks:
            rid = risk.get("id")
            for mitigation in risk.get("mitigations", []):
                if not isinstance(mitigation, dict):
                    continue
                mid = mitigation.get("id")
                if not mid:
                    continue
                if (rid, mid, "risk_to_mitigation") not in link_set:
                    errors.append(f"traceability missing {rid} -> mitigation {mid}")
                if not any(source == mid and target in test_ids and rel == "mitigation_to_test" for source, target, rel in link_set):
                    errors.append(f"mitigation {mid} lacks verification test trace")

    required_families = set(quality.get("risk_required_families", {}).get(risk_level, []))
    planned_families = set(packet.get("test_plan", {}).get("families", []))
    known_families = set(quality.get("test_families", []))
    if status in ASSURED_STATUSES:
        missing_families = sorted(required_families - planned_families)
        if missing_families:
            errors.append(f"test plan missing required {risk_level}-risk families: {missing_families}")
    unknown = sorted(planned_families - known_families)
    if unknown:
        errors.append(f"test plan has unknown families: {unknown}")

    for test in tests:
        tid = test.get("id", "<unknown>")
        family = test.get("family")
        if family not in known_families:
            errors.append(f"{tid}: unknown test family {family}")
        if family not in planned_families:
            errors.append(f"{tid}: test family {family} not declared in test_plan.families")
        if not test.get("covers"):
            warnings.append(f"{tid}: test has no declared coverage target")
        for target in test.get("covers", []):
            if target not in req_ids | ac_ids | risk_ids | mitigation_ids:
                errors.append(f"{tid}: covers unknown trace target {target}")

    if status in ASSURED_STATUSES:
        docs = packet.get("documentation_impact", {})
        if docs.get("declared") is not True:
            errors.append("documentation impact must be explicitly declared")
        arch = packet.get("architecture_impact", {})
        if arch.get("significant") is True and not arch.get("adr_ids"):
            errors.append("significant architecture impact requires ADR id(s)")
        if risk_level in {"high", "critical"}:
            release = packet.get("release", {})
            if not release.get("rollback_strategy"):
                errors.append(f"{risk_level}-risk work requires rollback_strategy")
            if not release.get("observability_plan"):
                errors.append(f"{risk_level}-risk work requires observability_plan")

    configured_profile = quality.get("profile")
    packet_profile = packet.get("quality_profile") or configured_profile
    if packet_profile not in quality.get("profiles", {}):
        errors.append(f"unknown quality_profile {packet_profile}")
    elif configured_profile in PROFILE_ORDER and packet_profile in PROFILE_ORDER and PROFILE_ORDER[packet_profile] < PROFILE_ORDER[configured_profile]:
        errors.append(f"quality_profile {packet_profile} cannot be lower than configured minimum {configured_profile}")

    if status in MERGE_STATUSES:
        candidate_sha = packet.get("candidate_sha")
        if not candidate_sha:
            errors.append("merge_ready/done packet requires candidate_sha")
        elif not SHA40.fullmatch(str(candidate_sha)):
            errors.append("candidate_sha must be a lowercase 40-hex commit SHA")

        if not isinstance(packet.get("code_change"), bool):
            errors.append("merge_ready/done packet requires explicit boolean code_change")

        sha = evidence.get("sha") if isinstance(evidence, dict) else None
        if not sha:
            errors.append("merge_ready/done packet requires exact evidence sha")
        elif candidate_sha and sha != candidate_sha:
            errors.append("evidence sha does not equal candidate_sha")

        verified_req = set(evidence.get("verified_requirements", [])) if isinstance(evidence, dict) else set()
        if req_ids - verified_req:
            errors.append(f"unverified requirements: {sorted(req_ids - verified_req)}")
        verified_ac = set(evidence.get("verified_acceptance_criteria", [])) if isinstance(evidence, dict) else set()
        if ac_ids - verified_ac:
            errors.append(f"unverified acceptance criteria: {sorted(ac_ids - verified_ac)}")

        if not evidence_artifacts:
            errors.append("merge_ready/done packet requires evidence.artifacts with stable ids")
        for tid in test_ids:
            if not any(source == tid and target in evidence_ids and rel == "test_to_evidence" for source, target, rel in link_set):
                errors.append(f"test {tid} lacks test_to_evidence trace to an existing evidence artifact")

        family_results = evidence.get("test_family_results", {}) if isinstance(evidence, dict) else {}
        for family in sorted(planned_families):
            if family_results.get(family) != "pass":
                errors.append(f"test family {family} must have pass evidence")

        if packet.get("code_change") is True and packet_profile in quality.get("profiles", {}):
            coverage = evidence.get("coverage", {}) if isinstance(evidence, dict) else {}
            thresholds = quality["profiles"][packet_profile]
            metric_map = {"line": "line_coverage_min", "branch": "branch_coverage_min", "changed_line": "changed_line_coverage_min", "mutation": "mutation_score_min"}
            for metric, threshold_key in metric_map.items():
                value = coverage.get(metric)
                threshold = thresholds.get(threshold_key)
                if not isinstance(value, (int, float)):
                    errors.append(f"coverage metric {metric} is required for code-changing {status} packet")
                elif isinstance(threshold, (int, float)) and value < threshold:
                    errors.append(f"coverage metric {metric}={value} is below {packet_profile} threshold {threshold}")

        gates = evidence.get("gates", {}) if isinstance(evidence, dict) else {}
        required_gates = {"requirements", "risk", "architecture", "code_quality", "functional_qa", "nonfunctional_qa", "documentation", "independent_review"}
        for gate in sorted(required_gates):
            if gates.get(gate) != "pass":
                errors.append(f"evidence gate {gate} must be pass")

        review = evidence.get("independent_review") if isinstance(evidence, dict) else None
        if not isinstance(review, dict):
            errors.append("merge_ready/done packet requires independent_review evidence")
        else:
            reviewer = review.get("actor")
            if not reviewer:
                errors.append("independent_review.actor is required")
            if reviewer in set(packet.get("material_authors", [])):
                errors.append(f"independent reviewer {reviewer} is a material author")
            if review.get("verdict") != "pass":
                errors.append("independent_review.verdict must be pass")
            if not candidate_sha or review.get("sha") != candidate_sha:
                errors.append("independent_review.sha must equal candidate_sha")

    return errors, warnings


def unique_ids(items: list, label: str, errors: list[str]) -> set[str]:
    result: set[str] = set()
    for item in items:
        ident = item.get("id") if isinstance(item, dict) else None
        if not ident:
            errors.append(f"{label} missing id")
        elif ident in result:
            errors.append(f"duplicate {label} id: {ident}")
        else:
            result.add(ident)
    return result


def print_matrix(packet: dict) -> None:
    print(f"Traceability matrix: {packet.get('work_unit', '?')}")
    print("SOURCE | RELATIONSHIP | TARGET")
    print("--- | --- | ---")
    for item in packet.get("traceability", []):
        print(f"{item.get('source','?')} | {item.get('relationship','?')} | {item.get('target','?')}")


def print_risks(packet: dict) -> None:
    print(f"Risk register: {packet.get('work_unit', '?')}")
    for item in sorted(packet.get("risks", []), key=lambda r: r.get("residual_score", 0), reverse=True):
        print(f"{item.get('id')} residual={item.get('residual_score')} owner={item.get('owner')} treatment={item.get('treatment')} status={item.get('status')} :: {item.get('title')}")


def evidence_manifest(packet: dict) -> dict:
    evidence = packet.get("evidence", {})
    tests = packet.get("test_plan", {}).get("tests", [])
    return {
        "work_unit": packet.get("work_unit"),
        "sha": evidence.get("sha") or packet.get("candidate_sha"),
        "quality_profile": packet.get("quality_profile") or load(CONTROL / "quality.json").get("profile"),
        "requirements": {"total": len(packet.get("requirements", [])), "verified": len(evidence.get("verified_requirements", []))},
        "acceptance_criteria": {"total": len(packet.get("acceptance_criteria", [])), "verified": len(evidence.get("verified_acceptance_criteria", []))},
        "risks": {"total": len(packet.get("risks", [])), "open": sum(1 for r in packet.get("risks", []) if r.get("status") == "open")},
        "tests": {"planned": len(tests), "families": sorted(set(t.get("family") for t in tests if t.get("family")))},
        "coverage": evidence.get("coverage", {}),
        "gates": evidence.get("gates", {}),
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="OneCompany engineering assurance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("policy")
    for name in ("validate", "trace", "risk", "evidence"):
        p = sub.add_parser(name)
        p.add_argument("packet", type=Path)
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
        print(json.dumps(evidence_manifest(packet), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
