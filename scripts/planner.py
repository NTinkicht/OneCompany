#!/usr/bin/env python3
"""Inspect OneCompany portfolio planning, priority, critical path, and safe parallel capacity."""
from __future__ import annotations

import argparse
import json
import sys

import knowledge
from lease_lifecycle import coordination_view
from onecompany_lib import CONTROL, load_json
from planning_lib import by_id, critical_path, priority_score, rank_work, select_parallel_set
from planning_validate import validate_documents


def active_leases() -> tuple[list[dict], set[str]]:
    view = coordination_view()
    return (
        [item for item in view.get("active_leases", []) if item.get("role") == "implementation"],
        set(view.get("verified_merged_work_units", view.get("merged_work_units", []))),
    )


def learning_preflight(work_item: dict) -> dict:
    """Return bounded advisory lessons automatically for a selected Work Unit."""
    tags = [
        str(work_item.get("work_kind") or "").lower(),
        str(work_item.get("risk_class") or "").lower(),
    ]
    tags.extend(str(ref).lower() for ref in work_item.get("planning_refs", []))
    tags = [tag for tag in tags if tag]
    return knowledge.preflight(
        query=str(work_item.get("title") or ""),
        tags=tags,
        files=[str(path) for path in work_item.get("write_scope", [])],
        risk=str(work_item.get("risk_class") or "").lower() or None,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("summary")
    sub.add_parser("rank")
    parallel = sub.add_parser("parallel")
    parallel.add_argument("--include-proposed", action="store_true")
    sub.add_parser("critical-path")
    explain = sub.add_parser("explain")
    explain.add_argument("id")
    args = parser.parse_args()

    planning = load_json(CONTROL / "planning.json")
    portfolio = load_json(CONTROL / "portfolio.json")
    catalog = load_json(CONTROL / "requirements-catalog.json")
    queue = load_json(CONTROL / "queue.json")
    work = queue.get("work_units", [])

    if args.command == "validate":
        errors, warnings = validate_documents()
        print(json.dumps({"valid": not errors, "errors": errors, "warnings": warnings}, indent=2))
        return 0 if not errors else 1
    if args.command == "summary":
        type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for entity in portfolio.get("entities", []):
            type_counts[entity.get("type", "UNKNOWN")] = type_counts.get(entity.get("type", "UNKNOWN"), 0) + 1
            status_counts[entity.get("status", "UNKNOWN")] = status_counts.get(entity.get("status", "UNKNOWN"), 0) + 1
        leases, done = active_leases()
        plan = select_parallel_set(work, planning, leases, done)
        print(json.dumps({
            "portfolio_entities": len(portfolio.get("entities", [])),
            "entity_types": type_counts,
            "entity_statuses": status_counts,
            "requirements": len(catalog.get("requirements", [])),
            "work_units": len(work),
            "active_implementation_streams": len(leases),
            "available_parallel_slots": plan["available_slots"],
            "safe_next_work": [item.get("id") for item in plan["selected"]],
        }, indent=2))
        return 0
    if args.command == "rank":
        ranked = rank_work(work, planning)
        critical_ids = set(critical_path(work).get("path", []))
        print(json.dumps([
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "score": round(priority_score(item, planning), 4),
                "priority": item.get("priority"),
                "critical_path": item.get("id") in critical_ids,
                "job_size": (item.get("estimate") or {}).get("job_size"),
            }
            for item in ranked
        ], indent=2))
        return 0
    if args.command == "parallel":
        leases, done = active_leases()
        result = select_parallel_set(work, planning, leases, done, args.include_proposed)
        result["selected"] = [
            {
                "id": item.get("id"),
                "score": round(priority_score(item, planning), 4),
                "write_scope": item.get("write_scope", []),
                "resource_locks": item.get("resource_locks", []),
                "learning_preflight": learning_preflight(item),
            }
            for item in result["selected"]
        ]
        result["ranked"] = [{"id": item.get("id"), "score": round(priority_score(item, planning), 4)} for item in result["ranked"]]
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "critical-path":
        print(json.dumps(critical_path(work), indent=2))
        return 0
    if args.command == "explain":
        identifier = args.id
        entity = next((e for e in portfolio.get("entities", []) if e.get("id") == identifier), None)
        requirement = next((r for r in catalog.get("requirements", []) if r.get("id") == identifier), None)
        work_item = by_id(work).get(identifier)
        links = [link for link in portfolio.get("links", []) if identifier in {link.get("source"), link.get("target")}]
        payload = {"id": identifier, "entity": entity, "requirement": requirement, "work_unit": work_item, "links": links}
        if work_item:
            payload["priority_score"] = round(priority_score(work_item, planning), 4)
            payload["critical_path"] = identifier in set(critical_path(work).get("path", []))
            payload["learning_preflight"] = learning_preflight(work_item)
        if not entity and not requirement and not work_item:
            payload["error"] = "unknown id"
            print(json.dumps(payload, indent=2)); return 2
        print(json.dumps(payload, indent=2)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
