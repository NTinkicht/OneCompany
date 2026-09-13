#!/usr/bin/env python3
"""Validate OneCompany portfolio taxonomy, planning graph, and execution-planning semantics."""
from __future__ import annotations

import re
import sys
from typing import Any

from onecompany_lib import CONTROL, ROOT, load_json
from planning_lib import by_id, critical_path

PREFIXES = {
    "OBJECTIVE": r"^OBJ-[0-9]{3,}$",
    "EPIC": r"^EPIC-[0-9]{3,}$",
    "FEATURE": r"^FEAT-[0-9]{3,}$",
    "CAPABILITY": r"^CAP-[0-9]{3,}$",
    "USER_STORY": r"^US-[0-9]{3,}$",
    "TASK": r"^TASK-[0-9]{3,}$",
    "SPIKE": r"^SPIKE-[0-9]{3,}$",
    "DEFECT": r"^(BUG|DEF)-[0-9]{3,}$",
    "ENABLER": r"^ENAB-[0-9]{3,}$",
    "MILESTONE": r"^MS-[0-9]{3,}$",
    "RELEASE": r"^REL-[0-9]{3,}$",
}
HIERARCHY_RELATIONS = {"contains", "decomposes_to"}


def _cycle_errors(graph: dict[str, list[str]], label: str) -> list[str]:
    errors: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            start = stack.index(node) if node in stack else 0
            errors.append(f"{label} cycle: " + " -> ".join(stack[start:] + [node]))
            return
        visiting.add(node)
        stack.append(node)
        for nxt in graph.get(node, []):
            visit(nxt)
        stack.pop()
        visiting.discard(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    return errors


def validate_documents() -> tuple[list[str], list[str]]:
    planning = load_json(CONTROL / "planning.json")
    portfolio = load_json(CONTROL / "portfolio.json")
    catalog = load_json(CONTROL / "requirements-catalog.json")
    queue = load_json(CONTROL / "queue.json")
    errors: list[str] = []
    warnings: list[str] = []

    configured_types = set(planning.get("work_model", {}).get("entity_types", []))
    entities = portfolio.get("entities", [])
    entity_map: dict[str, dict[str, Any]] = {}
    for entity in entities:
        entity_id = entity.get("id")
        entity_type = entity.get("type")
        if not isinstance(entity_id, str) or not entity_id:
            errors.append("portfolio entity missing id")
            continue
        if entity_id in entity_map:
            errors.append(f"duplicate portfolio entity id: {entity_id}")
        entity_map[entity_id] = entity
        if entity_type not in configured_types:
            errors.append(f"{entity_id}: unsupported entity type {entity_type!r}")
        pattern = PREFIXES.get(str(entity_type))
        if pattern and re.fullmatch(pattern, entity_id) is None:
            errors.append(f"{entity_id}: id does not match {entity_type} convention {pattern}")

    requirements = catalog.get("requirements", [])
    requirement_map: dict[str, dict[str, Any]] = {}
    req_pattern = re.compile(r"^(BR|UR|FR|NFR|SEC|DATA|OPS|UX|CON)-[0-9]{3,}$")
    for req in requirements:
        req_id = req.get("id")
        if not isinstance(req_id, str) or not req_pattern.fullmatch(req_id):
            errors.append(f"invalid requirement id: {req_id!r}")
            continue
        if req_id in requirement_map:
            errors.append(f"duplicate requirement id: {req_id}")
        requirement_map[req_id] = req
        if req.get("status") in {"approved", "implemented", "verified"} and not req.get("acceptance_criteria"):
            errors.append(f"{req_id}: baselined requirement must have acceptance criteria")

    work = queue.get("work_units", [])
    execution_types = set(planning.get("work_model", {}).get("execution_item_types", []))
    for item in work:
        if item.get("work_kind") not in execution_types:
            errors.append(f"{item.get('id')}: unsupported work_kind {item.get('work_kind')!r}")
    work_map = by_id(work)
    known = set(entity_map) | set(requirement_map) | set(work_map)
    relation_types = set(planning.get("work_model", {}).get("relationship_types", []))
    hierarchy_graph: dict[str, list[str]] = {}
    for link in portfolio.get("links", []):
        source, target, relation = link.get("source"), link.get("target"), link.get("relationship")
        if source not in known:
            errors.append(f"portfolio link has unknown source {source!r}")
        if target not in known:
            errors.append(f"portfolio link has unknown target {target!r}")
        if relation not in relation_types:
            errors.append(f"portfolio link {source}->{target}: unsupported relationship {relation!r}")
        if source == target:
            errors.append(f"portfolio link {source}: self-link forbidden")
        if relation in HIERARCHY_RELATIONS and isinstance(source, str) and isinstance(target, str):
            hierarchy_graph.setdefault(source, []).append(target)
            hierarchy_graph.setdefault(target, [])
    errors.extend(_cycle_errors(hierarchy_graph, "portfolio hierarchy"))

    trace_policy = planning.get("traceability", {})
    if trace_policy.get("ready_work_requires_parent_or_requirement", True):
        for item in work:
            if item.get("status") != "READY":
                continue
            planning_refs = item.get("planning_refs", [])
            requirement_ids = item.get("requirement_ids", [])
            if not planning_refs and not requirement_ids:
                errors.append(f"{item.get('id')}: READY work must trace to planning_refs or requirement_ids")
            for ref in planning_refs:
                if ref not in entity_map:
                    errors.append(f"{item.get('id')}: unknown planning_ref {ref}")
            for req_id in requirement_ids:
                if req_id not in requirement_map:
                    errors.append(f"{item.get('id')}: unknown requirement_id {req_id}")

    parallel = planning.get("parallel_execution", {})
    if parallel.get("enabled") and int(parallel.get("max_concurrent_implementation_streams", 1)) > 1:
        for item in work:
            if item.get("status") == "READY" and item.get("parallelism", "auto") != "serial" and not item.get("write_scope"):
                warnings.append(f"{item.get('id')}: no write_scope; it will be serialized conservatively")

    try:
        critical_path(work)
    except ValueError as exc:
        errors.append(str(exc))

    return errors, warnings


def main() -> int:
    try:
        errors, warnings = validate_documents()
    except Exception as exc:
        print(f"ERROR: planning validation could not load control plane: {exc}")
        return 1
    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Planning validation FAILED ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1
    print(f"Planning validation PASS ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
