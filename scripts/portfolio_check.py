#!/usr/bin/env python3
"""Deterministic, read-only multi-project isolation check (OC-P1-10 slice 1, #465).

Input: ``{"revision": 40-hex, "projects": [{"id", "repo": "owner/name", "queue_id", "budget_id",
"policy_id", "credential_ref", "preview_url" (optional)}], "leases": [{"id", "project", "repo"}], "approvals": [{"id",
"project", "scope_project"}], "accesses": [{"id", "project", "target_project",
"kind": data|credential|lease|approval}]}``.
A portfolio needs at least two projects on distinct repos; queues, budgets, policies and credentials
must never be shared between projects (nor may an optional preview URL); a lease must name its own project's repo; an approval must
scope only its own project; and no project may reach another project's data, credentials, leases or
approvals. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

HEX40 = re.compile(r"[0-9a-fA-F]{40}")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
PREVIEW = re.compile(r"https?://\S+", re.IGNORECASE)
KINDS = {"data", "credential", "lease", "approval"}
SHARED = (("queue_id", "SHARED_QUEUE"), ("budget_id", "SHARED_BUDGET"),
          ("policy_id", "SHARED_POLICY"), ("credential_ref", "SHARED_CREDENTIAL"))


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _in(value: object, allowed: set) -> bool:
    """Membership that is False (never TypeError) for non-string values."""
    return isinstance(value, str) and value in allowed


def _norm(value: str) -> str:
    """Identity form of a shared resource id: case and surrounding whitespace never make it distinct."""
    return value.strip().casefold()


def _preview_key(value: str) -> str | None:
    """Identity form of a preview URL, or None when it is not a valid http(s) URL with a host.

    Case, surrounding whitespace, trailing slashes, a fragment and the scheme's default port never make it distinct.
    """
    text = value.strip()
    if not PREVIEW.fullmatch(text):
        return None
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return None
    if port is not None and port != {"http": 80, "https": 443}[scheme]:
        host = f"{host}:{port}"
    query = f"?{parts.query}" if parts.query else ""
    return f"{scheme}://{host}{parts.path.casefold().rstrip('/')}{query.casefold()}"


def _repo_key(value: str) -> str:
    """Identity form of a repo: GitHub ignores case and a trailing .git."""
    key = value.strip().lower()
    return key[:-4] if key.endswith(".git") else key


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
        if "preview_url" in p and (not isinstance(p["preview_url"], str)
                                   or _preview_key(p["preview_url"]) is None):
            raise ValueError(f"{p['id']} preview_url must be an http(s) URL")
    for l in leases:
        if not _in(l.get("project"), ids):
            raise ValueError(f"{l['id']} references an unknown project")
        if not isinstance(l.get("repo"), str) or not REPO.fullmatch(l["repo"]):
            raise ValueError(f"{l['id']} repo must be owner/name")
    for a in approvals:
        if not _in(a.get("project"), ids) or not _in(a.get("scope_project"), ids):
            raise ValueError(f"{a['id']} references an unknown project")
    for x in accesses:
        if not _in(x.get("project"), ids) or not _in(x.get("target_project"), ids):
            raise ValueError(f"{x['id']} references an unknown project")
        if not _in(x.get("kind"), KINDS):
            raise ValueError(f"{x['id']} has unknown kind")
    return data


def evaluate(report: dict) -> dict:
    problems: list[str] = []
    projects = report["projects"]
    if len(projects) < 2:
        problems.append("SINGLE_PROJECT a portfolio needs at least two projects")
    by_repo: dict[str, list[str]] = {}
    for p in projects:
        by_repo.setdefault(_repo_key(p["repo"]), []).append(p["id"])
    for repo, owners in sorted(by_repo.items()):
        if len(owners) > 1:
            problems.append(f"DUPLICATE_REPO {repo} used by {','.join(sorted(owners))}")
    for field, code in SHARED:
        owners: dict[str, list[str]] = {}
        for p in projects:
            owners.setdefault(_norm(p[field]), []).append(p["id"])
        for value, ids in sorted(owners.items()):
            if len(ids) > 1:
                problems.append(f"{code} {value} shared by {','.join(sorted(ids))}")
    previews: dict[str, list[str]] = {}
    for p in projects:
        if "preview_url" in p:
            previews.setdefault(_preview_key(p["preview_url"]), []).append(p["id"])
    for value, ids in sorted(previews.items()):
        if len(ids) > 1:
            problems.append(f"SHARED_PREVIEW {value} shared by {','.join(sorted(ids))}")
    repo_of = {p["id"]: _repo_key(p["repo"]) for p in projects}
    for l in report["leases"]:
        if _repo_key(l["repo"]) != repo_of[l["project"]]:
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
