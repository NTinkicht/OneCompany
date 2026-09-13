#!/usr/bin/env python3
"""Validate OneCompany portfolio taxonomy, requirements, risks, traceability, and execution planning."""
from __future__ import annotations

import re
import sys
from typing import Any

from onecompany_lib import CONTROL, load_json
from planning_lib import by_id, critical_path

PREFIXES = {
    "OBJECTIVE": r"^OBJ-[0-9]{3,}$", "EPIC": r"^EPIC-[0-9]{3,}$", "FEATURE": r"^FEAT-[0-9]{3,}$",
    "CAPABILITY": r"^CAP-[0-9]{3,}$", "USER_STORY": r"^US-[0-9]{3,}$", "MILESTONE": r"^MS-[0-9]{3,}$",
    "RELEASE": r"^REL-[0-9]{3,}$",
}
HIERARCHY_RELATIONS = {"contains", "decomposes_to"}
ACTIVE_OR_DELIVERED = {"READY", "LEASED", "IN_PROGRESS", "CI_PENDING", "REVIEW_PENDING", "REMEDIATION", "MERGE_READY", "MERGED", "DONE"}
PARENT_TO_WU_RELATIONS = {"contains", "decomposes_to", "delivers", "realizes", "scheduled_for"}
REQUIREMENT_TO_WU_RELATIONS = {"implements", "realizes", "satisfies", "delivers"}
PLANNING_TO_REQUIREMENT_RELATIONS = {"traces_to", "targets", "contains", "decomposes_to"}


def _cycle_errors(graph: dict[str, list[str]], label: str) -> list[str]:
    errors: list[str] = []; visiting: set[str] = set(); visited: set[str] = set(); stack: list[str] = []
    def visit(node: str) -> None:
        if node in visited: return
        if node in visiting:
            start = stack.index(node) if node in stack else 0; errors.append(f"{label} cycle: " + " -> ".join(stack[start:] + [node])); return
        visiting.add(node); stack.append(node)
        for nxt in graph.get(node, []): visit(nxt)
        stack.pop(); visiting.discard(node); visited.add(node)
    for node in sorted(graph): visit(node)
    return errors


def validate_documents() -> tuple[list[str], list[str]]:
    planning = load_json(CONTROL / "planning.json"); portfolio = load_json(CONTROL / "portfolio.json")
    catalog = load_json(CONTROL / "requirements-catalog.json"); risk_register = load_json(CONTROL / "risk-register.json")
    queue = load_json(CONTROL / "queue.json"); req_policy = load_json(CONTROL / "requirements.json"); risk_policy = load_json(CONTROL / "risk.json")
    errors: list[str] = []; warnings: list[str] = []

    configured_types = set(planning.get("work_model", {}).get("entity_types", [])); entities = portfolio.get("entities", [])
    entity_map: dict[str, dict[str, Any]] = {}
    for entity in entities:
        entity_id = entity.get("id"); entity_type = entity.get("type")
        if not isinstance(entity_id, str) or not entity_id: errors.append("portfolio entity missing id"); continue
        if entity_id in entity_map: errors.append(f"duplicate portfolio entity id: {entity_id}")
        entity_map[entity_id] = entity
        if entity_type not in configured_types: errors.append(f"{entity_id}: unsupported entity type {entity_type!r}")
        pattern = PREFIXES.get(str(entity_type))
        if pattern and re.fullmatch(pattern, entity_id) is None: errors.append(f"{entity_id}: id does not match {entity_type} convention {pattern}")
        if entity.get("status") in {"READY", "ACTIVE"} and entity_type == "OBJECTIVE" and not entity.get("target_metric"):
            errors.append(f"{entity_id}: active/ready objective requires target_metric")

    ac_map: dict[str, dict[str, Any]] = {}
    for ac in catalog.get("acceptance_criteria", []):
        ac_id = ac.get("id")
        if not isinstance(ac_id, str) or re.fullmatch(r"^AC-[0-9]{3,}$", ac_id) is None: errors.append(f"invalid acceptance criterion id: {ac_id!r}"); continue
        if ac_id in ac_map: errors.append(f"duplicate acceptance criterion id: {ac_id}")
        ac_map[ac_id] = ac
        if ac.get("status") in {"approved", "verified"} and not str(ac.get("statement", "")).strip(): errors.append(f"{ac_id}: baselined acceptance criterion requires statement")

    requirements = catalog.get("requirements", []); requirement_map: dict[str, dict[str, Any]] = {}
    req_pattern = re.compile(r"^(BR|UR|FR|NFR|SEC|DATA|OPS|UX|CON)-[0-9]{3,}$")
    avoid = [str(word).lower() for word in req_policy.get("language_rules", {}).get("avoid", [])]
    mandatory = req_policy.get("mandatory_attributes", [])
    for req in requirements:
        req_id = req.get("id")
        if not isinstance(req_id, str) or not req_pattern.fullmatch(req_id): errors.append(f"invalid requirement id: {req_id!r}"); continue
        if req_id in requirement_map: errors.append(f"duplicate requirement id: {req_id}")
        requirement_map[req_id] = req
        for field in mandatory:
            if field not in req or req.get(field) in (None, "", []):
                if field == "risk_ids" and not req.get("risk_ids"): continue
                errors.append(f"{req_id}: requirement missing {field}")
        statement = str(req.get("statement", "")); lowered = f" {statement.lower()} "
        if req.get("status") in {"approved", "implemented", "verified"}:
            if lowered.count(" shall ") != 1: errors.append(f"{req_id}: baselined requirement must contain exactly one normative 'shall'")
            for term in avoid:
                if term and term in statement.lower(): errors.append(f"{req_id}: ambiguous/discouraged term '{term}'")
            if not req.get("acceptance_criteria"): errors.append(f"{req_id}: baselined requirement must have acceptance criteria")
        if req.get("type") == "nonfunctional" and req.get("status") in {"approved", "implemented", "verified"}:
            measure = req.get("nfr_measure")
            if not isinstance(measure, dict) or not all(measure.get(key) for key in ("metric", "target", "method", "conditions")):
                errors.append(f"{req_id}: baselined nonfunctional requirement requires metric/target/method/conditions")
        for ac_id in req.get("acceptance_criteria", []):
            if ac_id not in ac_map: errors.append(f"{req_id}: references unknown acceptance criterion {ac_id}")
        for dep in req.get("depends_on", []):
            if dep == req_id: errors.append(f"{req_id}: self dependency is forbidden")

    risk_map: dict[str, dict[str, Any]] = {}; domains = set(risk_policy.get("domains", []))
    for risk in risk_register.get("risks", []):
        risk_id = risk.get("id")
        if not isinstance(risk_id, str) or re.fullmatch(r"^RISK-[0-9]{3,}$", risk_id) is None: errors.append(f"invalid risk id: {risk_id!r}"); continue
        if risk_id in risk_map: errors.append(f"duplicate risk id: {risk_id}")
        risk_map[risk_id] = risk
        if risk.get("domain") not in domains: errors.append(f"{risk_id}: unknown risk domain {risk.get('domain')!r}")
        inherent = int(risk.get("likelihood", 0) or 0) * int(risk.get("impact", 0) or 0)
        residual = int(risk.get("residual_likelihood", 0) or 0) * int(risk.get("residual_impact", 0) or 0)
        if risk.get("inherent_score") != inherent: errors.append(f"{risk_id}: inherent_score must equal likelihood*impact ({inherent})")
        if risk.get("residual_score") != residual: errors.append(f"{risk_id}: residual_score must equal residual_likelihood*residual_impact ({residual})")
        if residual >= 17:
            acceptance = risk.get("acceptance")
            if risk.get("treatment") == "accept" and (not isinstance(acceptance, dict) or acceptance.get("human") is not True or not acceptance.get("approved_by")):
                errors.append(f"{risk_id}: critical residual-risk acceptance requires explicit human approval")
    for req_id, req in requirement_map.items():
        for risk_id in req.get("risk_ids", []):
            if risk_id not in risk_map: errors.append(f"{req_id}: references unknown planning risk {risk_id}")
        for dep in req.get("depends_on", []):
            if dep not in requirement_map: errors.append(f"{req_id}: depends_on unknown requirement {dep}")

    work = queue.get("work_units", []); execution_types = set(planning.get("work_model", {}).get("execution_item_types", []))
    for item in work:
        if item.get("work_kind") not in execution_types: errors.append(f"{item.get('id')}: unsupported work_kind {item.get('work_kind')!r}")
    work_map = by_id(work); known = set(entity_map) | set(requirement_map) | set(work_map)
    relation_types = set(planning.get("work_model", {}).get("relationship_types", [])); hierarchy_graph: dict[str, list[str]] = {}; link_keys: set[tuple[str, str, str]] = set()
    for link in portfolio.get("links", []):
        source, target, relation = link.get("source"), link.get("target"), link.get("relationship")
        key = (str(source), str(target), str(relation))
        if key in link_keys: errors.append(f"duplicate portfolio link {source}->{target} ({relation})")
        link_keys.add(key)
        if source not in known: errors.append(f"portfolio link has unknown source {source!r}")
        if target not in known: errors.append(f"portfolio link has unknown target {target!r}")
        if relation not in relation_types: errors.append(f"portfolio link {source}->{target}: unsupported relationship {relation!r}")
        if source == target: errors.append(f"portfolio link {source}: self-link forbidden")
        if relation in HIERARCHY_RELATIONS and isinstance(source, str) and isinstance(target, str):
            hierarchy_graph.setdefault(source, []).append(target); hierarchy_graph.setdefault(target, [])
    errors.extend(_cycle_errors(hierarchy_graph, "portfolio hierarchy"))

    for req_id, req in requirement_map.items():
        if req.get("status") in {"approved", "implemented", "verified"}:
            if not any(target == req_id and source in entity_map and rel in PLANNING_TO_REQUIREMENT_RELATIONS for source, target, rel in link_keys):
                errors.append(f"{req_id}: baselined requirement lacks planning-parent trace")

    trace_policy = planning.get("traceability", {})
    for item in work:
        if item.get("status") not in ACTIVE_OR_DELIVERED: continue
        wu_id = item.get("id"); planning_refs = item.get("planning_refs", []); requirement_ids = item.get("requirement_ids", [])
        if trace_policy.get("ready_work_requires_parent_or_requirement", True) and not planning_refs and not requirement_ids:
            errors.append(f"{wu_id}: active/delivered work must trace to planning_refs or requirement_ids")
        for ref in planning_refs:
            if ref not in entity_map: errors.append(f"{wu_id}: unknown planning_ref {ref}")
            elif not any(source == ref and target == wu_id and rel in PARENT_TO_WU_RELATIONS for source, target, rel in link_keys):
                errors.append(f"{wu_id}: planning_ref {ref} lacks reverse portfolio link to WU")
        for req_id in requirement_ids:
            req = requirement_map.get(req_id)
            if req is None: errors.append(f"{wu_id}: unknown requirement_id {req_id}")
            else:
                if req.get("status") not in {"approved", "implemented", "verified"}: errors.append(f"{wu_id}: requirement {req_id} is not approved/baselined")
                if not any(source == req_id and target == wu_id and rel in REQUIREMENT_TO_WU_RELATIONS for source, target, rel in link_keys):
                    errors.append(f"{wu_id}: requirement {req_id} lacks reverse portfolio link to WU")
        if item.get("status") == "BLOCKED":
            if not item.get("blocked_reason"): errors.append(f"{wu_id}: BLOCKED work requires blocked_reason")
            if not item.get("blocked_owner"): errors.append(f"{wu_id}: BLOCKED work requires blocked_owner")

    referenced_acs = {ac_id for req in requirements for ac_id in req.get("acceptance_criteria", [])}
    for ac_id, ac in ac_map.items():
        if ac.get("status") != "retired" and ac_id not in referenced_acs: warnings.append(f"{ac_id}: acceptance criterion is orphaned")

    parallel = planning.get("parallel_execution", {})
    if parallel.get("enabled") and int(parallel.get("max_concurrent_implementation_streams", 1)) > 1:
        for item in work:
            if item.get("status") in ACTIVE_OR_DELIVERED and item.get("parallelism", "auto") != "serial" and not item.get("write_scope"):
                warnings.append(f"{item.get('id')}: no write_scope; it will be serialized conservatively")

    try: critical_path(work)
    except ValueError as exc: errors.append(str(exc))
    return errors, warnings


def main() -> int:
    try: errors, warnings = validate_documents()
    except Exception as exc: print(f"ERROR: planning validation could not load control plane: {exc}"); return 1
    for warning in warnings: print(f"WARN: {warning}")
    if errors:
        for error in errors: print(f"ERROR: {error}")
        print(f"Planning validation FAILED ({len(errors)} error(s), {len(warnings)} warning(s))."); return 1
    print(f"Planning validation PASS ({len(warnings)} warning(s))."); return 0


if __name__ == "__main__":
    sys.exit(main())
