#!/usr/bin/env python3
"""Deterministic, read-only multi-project isolation check (OC-P1-10 slice 1, #465).

Input: ``{"revision": 40-hex, "projects": [{"id", "repo": "owner/name", "queue_id", "budget_id",
"policy_id", "credential_ref"}], "leases": [{"id", "project", "repo"}], "approvals": [{"id",
"project", "scope_project"}], "accesses": [{"id", "project", "target_project",
"kind": data|credential|lease|approval}]}``.
A portfolio needs at least two projects on distinct repos; queues, budgets, policies and credentials
must never be shared between projects; a lease must name its own project's repo; an approval must
scope only its own project; and no project may reach another project's data, credentials, leases or
approvals. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-fA-F]{40}")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
KINDS = {"data", "credential", "lease", "approval"}
SHARED = (("queue_id", "SHARED_QUEUE"), ("budget_id", "SHARED_BUDGET"),
          ("policy_id", "SHARED_POLICY"), ("credential_ref", "SHARED_CREDENTIAL"))


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(data: dict, key: str) -> list:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _unique_ids(items: list, label: str) -> None:
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not _name(item.get("id")):
            raise ValueError(f"{label} needs a non-empty string id")
        if item["id"] in seen:
            raise ValueError(f"duplicate {label} id: {item['id']}")
        seen.add(item["id"])


def load_report(path: Path) -> dict:
    """Return the validated report; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"report unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("report is not an object")
    if not isinstance(data.get("revision"), str) or not HEX40.fullmatch(data["revision"]):
        raise ValueError("report needs a 40-hex revision")
    projects, leases = _list(data, "projects"), _list(data, "leases")
    approvals, accesses = _list(data, "approvals"), _list(data, "accesses")
    for items, label in ((projects, "project"), (leases, "lease"), (approvals, "approval"), (accesses, "access")):
        _unique_ids(items, label)
    ids = {p["id"] for p in projects}
    for p in projects:
        if not isinstance(p.get("repo"), str) or not REPO.fullmatch(p["repo"]):
            raise ValueError(f"{p['id']} repo must be owner/name")
        for field, _ in SHARED:
            if not _name(p.get(field)):
                raise ValueError(f"{p['id']} {field} must be a non-empty string")
    for l in leases:
        if l.get("project") not in ids:
            raise ValueError(f"{l['id']} references an unknown project")
        if not isinstance(l.get("repo"), str) or not REPO.fullmatch(l["repo"]):
            raise ValueError(f"{l['id']} repo must be owner/name")
    for a in approvals:
        if a.get("project") not in ids or a.get("scope_project") not in ids:
            raise ValueError(f"{a['id']} references an unknown project")
    for x in accesses:
        if x.get("project") not in ids or x.get("target_project") not in ids:
            raise ValueError(f"{x['id']} references an unknown project")
        if x.get("kind") not in KINDS:
            raise ValueError(f"{x['id']} has unknown kind")
    return data


def evaluate(report: dict) -> dict:
    problems: list[str] = []
    projects = report["projects"]
    if len(projects) < 2:
        problems.append("SINGLE_PROJECT a portfolio needs at least two projects")
    by_repo: dict[str, list[str]] = {}
    for p in projects:
        by_repo.setdefault(p["repo"].lower(), []).append(p["id"])
    for repo, owners in sorted(by_repo.items()):
        if len(owners) > 1:
            problems.append(f"DUPLICATE_REPO {repo} used by {','.join(sorted(owners))}")
    for field, code in SHARED:
        owners: dict[str, list[str]] = {}
        for p in projects:
            owners.setdefault(p[field], []).append(p["id"])
        for value, ids in sorted(owners.items()):
            if len(ids) > 1:
                problems.append(f"{code} {value} shared by {','.join(sorted(ids))}")
    repo_of = {p["id"]: p["repo"].lower() for p in projects}
    for l in report["leases"]:
        if l["repo"].lower() != repo_of[l["project"]]:
            problems.append(f"LEASE_CROSS_TARGET {l['id']} lease for {l['project']} names repo {l['repo']}")
    for a in report["approvals"]:
        if a["scope_project"] != a["project"]:
            problems.append(f"APPROVAL_CROSS_TARGET {a['id']} approval of {a['project']} scopes {a['scope_project']}")
    for x in report["accesses"]:
        if x["target_project"] != x["project"]:
            problems.append(f"CROSS_TARGET_ACCESS {x['id']} {x['project']} reaches {x['kind']} of {x['target_project']}")
    return {"projects": len(projects), "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only multi-project isolation check.")
    parser.add_argument("report", help="portfolio report JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load_report(Path(args.report)))
    except ValueError as exc:
        print(f"portfolio-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"portfolio-check: {result['projects']} projects, {len(result['problems'])} problems")
        for item in result["problems"]:
            print(f"  {item}")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
