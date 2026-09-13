#!/usr/bin/env python3
"""Dependency-free OneCompany engineering assurance validator and reporter."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTROL = ROOT / ".onecompany"

POLICY_FILES = ["quality.json", "requirements.json", "risk.json", "traceability.json", "architecture.json", "waivers.json", "quality-baseline.json"]
REQUIRED_PACKET = ["work_unit", "status", "objective", "risk_level", "requirements", "acceptance_criteria", "risks", "traceability", "test_plan", "documentation_impact", "architecture_impact", "release", "evidence"]


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

    risk_level = packet.get("risk_level")
    if risk_level not in {"low", "medium", "high", "critical"}:
        errors.append("risk_level must be low|medium|high|critical")
        risk_level = "low"

    req_policy = load(CONTROL / "requirements.json")
    quality = load(CONTROL / "quality.json")
    risk_policy = load(CONTROL / "risk.json")

    reqs = packet.get("requirements", [])
    acs = packet.get("acceptance_criteria", [])
    risks = packet.get("risks", [])
    links = packet.get("traceability", [])
    tests = packet.get("test_plan", {}).get("tests", [])

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
        statement = str(req.get("statement", ""))
        if " shall " not in f" {statement.lower()} ":
            errors.append(f"{rid}: formal requirement must use 'shall'")
        lowered = statement.lower()
        for term in avoid:
            if term and term in lowered:
                errors.append(f"{rid}: ambiguous/discouraged term '{term}'")
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
    for risk in risks:
        rid = risk.get("id", "<unknown>")
        for field in risk_policy.get("mandatory_attributes", []):
            if field not in risk or risk.get(field) in (None, "", []):
                errors.append(f"{rid}: risk missing {field}")
        if risk.get("domain") not in domains:
            errors.append(f"{rid}: unknown risk domain {risk.get('domain')}")
        inherent = risk.get("likelihood", 0) * risk.get("impact", 0)
        residual = risk.get("residual_likelihood", 0) * risk.get("residual_impact", 0)
        if risk.get("inherent_score") != inherent:
            errors.append(f"{rid}: inherent_score must equal likelihood*impact ({inherent})")
        if risk.get("residual_score") != residual:
            errors.append(f"{rid}: residual_score must equal residual_likelihood*residual_impact ({residual})")
        if residual >= 17:
            acceptance = risk.get("acceptance")
            if not isinstance(acceptance, dict) or not acceptance.get("human") or not acceptance.get("approved_by"):
                errors.append(f"{rid}: critical residual risk requires explicit human acceptance")
        if residual >= 10 and not risk.get("owner"):
            errors.append(f"{rid}: high residual risk requires owner")

    link_set = {(str(x.get("source")), str(x.get("target")), str(x.get("relationship"))) for x in links}
    for req in reqs:
        rid = req.get("id")
        for ac in req.get("acceptance_criteria", []):
            if (rid, ac, "requirement_to_acceptance_criterion") not in link_set:
                errors.append(f"traceability missing {rid} -> {ac}")
        if not any(source == rid and rel == "requirement_to_test" for source, _, rel in link_set):
            errors.append(f"traceability missing requirement_to_test for {rid}")
        if not any(source == rid and rel == "requirement_to_work_unit" for source, _, rel in link_set):
            errors.append(f"traceability missing requirement_to_work_unit for {rid}")

    for risk in risks:
        rid = risk.get("id")
        residual = risk.get("residual_score", 0)
        for mitigation in risk.get("mitigations", []):
            mid = mitigation.get("id") if isinstance(mitigation, dict) else mitigation
            if not mid:
                errors.append(f"{rid}: mitigation must have stable id")
                continue
            if (rid, mid, "risk_to_mitigation") not in link_set:
                errors.append(f"traceability missing {rid} -> mitigation {mid}")
            if residual >= 10 and not any(source == mid and rel == "mitigation_to_test" for source, _, rel in link_set):
                errors.append(f"high/critical {rid}: mitigation {mid} lacks verification test trace")

    required_families = set(quality.get("risk_required_families", {}).get(risk_level, []))
    planned_families = set(packet.get("test_plan", {}).get("families", []))
    missing_families = sorted(required_families - planned_families)
    if missing_families:
        errors.append(f"test plan missing required {risk_level}-risk families: {missing_families}")
    known_families = set(quality.get("test_families", []))
    unknown = sorted(planned_families - known_families)
    if unknown:
        errors.append(f"test plan has unknown families: {unknown}")

    for test in tests:
        tid = test.get("id", "<unknown>")
        if test.get("family") not in known_families:
            errors.append(f"{tid}: unknown test family {test.get('family')}")
        if not test.get("covers"):
            warnings.append(f"{tid}: test has no declared coverage target")

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

    status = packet.get("status")
    if status in {"merge_ready", "done"}:
        evidence = packet.get("evidence", {})
        sha = evidence.get("sha")
        if not sha:
            errors.append("merge_ready/done packet requires exact evidence sha")
        if packet.get("candidate_sha") and sha != packet.get("candidate_sha"):
            errors.append("evidence sha does not equal candidate_sha")
        verified_req = set(evidence.get("verified_requirements", []))
        if req_ids - verified_req:
            errors.append(f"unverified requirements: {sorted(req_ids - verified_req)}")
        verified_ac = set(evidence.get("verified_acceptance_criteria", []))
        if ac_ids - verified_ac:
            errors.append(f"unverified acceptance criteria: {sorted(ac_ids - verified_ac)}")
        gates = evidence.get("gates", {})
        required_gates = {"requirements", "risk", "architecture", "code_quality", "functional_qa", "nonfunctional_qa", "documentation", "independent_review"}
        for gate in sorted(required_gates):
            if gates.get(gate) != "pass":
                errors.append(f"evidence gate {gate} must be pass")

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
        "quality_profile": load(CONTROL / "quality.json").get("profile"),
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
