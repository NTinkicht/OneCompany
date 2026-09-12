#!/usr/bin/env python3
"""Report capability-level actor readiness without exposing credentials."""
from __future__ import annotations

import argparse
import json
import sys

from onecompany_lib import CONTROL, command_exists, load_json, run

LOCAL_PROBES = {
    "codex": ["codex", "--version"],
    "claude": ["claude", "--version"],
    "gemini-cli": ["gemini", "--version"],
    "mistral-vibe": ["vibe", "--version"],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect OneCompany actor readiness")
    parser.add_argument("--actor", help="Only show one actor ID")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--local-probe", action="store_true", help="Run non-inference local version/auth probes")
    args = parser.parse_args()

    actors_doc = load_json(CONTROL / "actors.json")
    readiness_doc = load_json(CONTROL / "readiness.json")
    actors = {item["id"]: item for item in actors_doc.get("actors", [])}
    ready = {item["actor_id"]: item for item in readiness_doc.get("actors", [])}

    rows = []
    for actor_id, actor in actors.items():
        if args.actor and actor_id != args.actor:
            continue
        status = ready.get(actor_id, {})
        row = {
            "actor": actor_id,
            "enabled": bool(actor.get("enabled")),
            "configured": bool(actor.get("configured")),
            "setup_state": status.get("setup_state", "missing"),
            "verified_surfaces": status.get("verified_surfaces", []),
            "verified_capabilities": status.get("verified_capabilities", []),
            "temporarily_unavailable_capabilities": status.get("temporarily_unavailable_capabilities", []),
            "repository_access": status.get("repository_access", {}),
            "unattended": status.get("unattended", {}),
            "last_verified_at": status.get("last_verified_at"),
            "evidence": status.get("evidence", []),
        }
        if args.local_probe:
            probe = LOCAL_PROBES.get(actor_id)
            if probe:
                if command_exists(probe[0]):
                    result = run(probe)
                    text = (result.stdout or result.stderr).strip().splitlines()
                    row["local_probe"] = {
                        "available": result.returncode == 0,
                        "command": probe[0],
                        "detail": text[0][:200] if text else f"exit={result.returncode}",
                    }
                else:
                    row["local_probe"] = {"available": False, "command": probe[0], "detail": "not installed/on PATH"}
            elif actor_id in {"chatgpt", "github-copilot"}:
                row["local_probe"] = {"available": None, "detail": "verify through product/GitHub surface"}
        rows.append(row)

    if args.local_probe:
        if command_exists("gh"):
            gh = run(["gh", "auth", "status"])
            gh_probe = {"available": gh.returncode == 0, "detail": "authenticated" if gh.returncode == 0 else "not authenticated"}
        else:
            gh_probe = {"available": False, "detail": "gh not installed"}
    else:
        gh_probe = None

    if args.json:
        print(json.dumps({"actors": rows, "github_cli": gh_probe}, indent=2))
    else:
        print("OneCompany actor readiness")
        for row in rows:
            caps = ",".join(row["verified_capabilities"]) or "none"
            blocked = ",".join(row["temporarily_unavailable_capabilities"]) or "none"
            access = row["repository_access"]
            access_text = ",".join(name for name in ("read", "write", "review", "merge") if access.get(name)) or "none"
            print(f"- {row['actor']}: state={row['setup_state']} enabled={row['enabled']} configured={row['configured']}")
            print(f"  verified_capabilities={caps}")
            print(f"  temporarily_unavailable={blocked}")
            print(f"  repository_access={access_text}")
            if args.local_probe and row.get("local_probe"):
                print(f"  local_probe={row['local_probe']['detail']}")
        if gh_probe is not None:
            print(f"- github_cli: {gh_probe['detail']}")

    if args.actor and not rows:
        print(f"unknown actor: {args.actor}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
