#!/usr/bin/env python3
"""Propose role-to-LLM assignments from a declared set of subscriptions.

Read-only by default. The output is a PROPOSAL: every assignment is
UNQUALIFIED, nothing is enabled, and no provider is invoked. No network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from product_brief import save_exclusive  # noqa: E402  (anchored, exclusive, 0600 export)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".onecompany"
HUMAN = "human-owner"
INCLUDED = "INCLUDED_SUBSCRIPTION"
ALIASES = {"copilot": "github-copilot", "gemini": "gemini-cli", "mistral": "mistral-vibe",
           "grok": "grok-4-6-interactive"}
SETUP_PAGE = {"copilot": "copilot.md", "github-copilot": "copilot.md", "grok-4-6-interactive": "custom-agent.md"}
AUTHOR_ROLES = ("implementer", "ci_remediator")
INDEPENDENT_ROLES = ("independent_reviewer", "security_reviewer")


def load(name: str) -> dict[str, Any]:
    """Read one committed OneCompany configuration file."""
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def parse_declared(raw: str, actors: dict[str, dict[str, Any]]) -> list[str]:
    """Return canonical actor ids, rejecting empty, unknown, human and duplicate names."""
    names = [part.strip() for part in raw.split(",")]
    if not raw.strip() or any(not name for name in names):
        raise ValueError("declaration must be a non-empty comma-separated list of actors")
    result: list[str] = []
    for name in names:
        actor = ALIASES.get(name, name)
        if actor == HUMAN:
            raise ValueError("human-owner is always available and is not declared")
        if actor not in actors:
            raise ValueError("unknown actor: " + name)
        if actor in result:
            raise ValueError("duplicate actor: " + name)
        result.append(actor)
    return result


def pick(capabilities: list[str], pool: set[str], routing: dict[str, list[str]],
         actors: dict[str, dict[str, Any]], banned: set[str]) -> str | None:
    """First actor by routing preference in the pool that has every capability."""
    for actor in routing.get(capabilities[0], []):
        if actor in pool and actor not in banned and all(c in actors[actor]["capabilities"] for c in capabilities):
            return actor
    return None


def build_plan(declared: list[str]) -> dict[str, Any]:
    """Deterministically map each role to a declared included-subscription actor or the human."""
    actors = {a["id"]: a for a in load("actors.json")["actors"]}
    roles = load("roles.json")["roles"]
    routing = load("routing.json")["preference_by_capability"]
    budget = load("budget.json")["ai"]
    if budget["additional_monthly_spend_cap"] != 0 or budget["allow_paid_fallback"]:
        raise ValueError("budget.json allows additional spend; the wizard refuses to plan")
    pool = {a for a in declared if actors[a]["cost_class"] == INCLUDED}
    excluded = [{"actor": a, "cost_class": actors[a]["cost_class"], "reason": "only INCLUDED_SUBSCRIPTION is considered"}
                for a in sorted(declared) if a not in pool]
    solo = len(pool) < 2
    assignment: dict[str, str] = {}
    notes: dict[str, str] = {}
    by_id = {r["id"]: r for r in roles}
    order = [r for r in AUTHOR_ROLES if r in by_id] + [r["id"] for r in roles if r["id"] not in AUTHOR_ROLES]
    for role_id in order:
        caps = by_id[role_id]["required_capabilities"]
        banned: set[str] = set()
        if role_id in INDEPENDENT_ROLES:
            banned = {assignment[r] for r in AUTHOR_ROLES if r in assignment}
        actor = None if (solo and (role_id in INDEPENDENT_ROLES or role_id == "merge_executor")) \
            else pick(caps, pool, routing, actors, banned)
        if actor is None:
            actor = HUMAN
            notes[role_id] = ("fewer than two distinct included-subscription actors; the human owner takes this role"
                              if solo and (role_id in INDEPENDENT_ROLES or role_id == "merge_executor")
                              else "no declared eligible actor; the human owner takes this role")
        assignment[role_id] = actor
    for role_id in INDEPENDENT_ROLES:
        if role_id in assignment and assignment[role_id] != HUMAN:
            if assignment[role_id] in {assignment[r] for r in AUTHOR_ROLES if r in assignment}:
                raise ValueError("internal independence violation")
    rows = []
    for role_id in [r["id"] for r in roles]:
        actor = assignment[role_id]
        page = SETUP_PAGE.get(actor, actor + ".md")
        rows.append({"role": role_id, "actor": actor, "status": "UNQUALIFIED", "note": notes.get(role_id, ""),
                     "qualification": "python onecompany.py qualify-worker --json; docs/agent-setup/" + page})
    warnings = []
    if solo:
        warnings.append("Fewer than two distinct included-subscription actors declared: independent review "
                        "and merge fall back to the human owner. One LLM can never review its own work.")
    return {"authorization": "NOT_GRANTED", "proposal_only": True, "additional_spend": 0,
            "declared": sorted(declared), "excluded": excluded, "assignments": rows, "warnings": warnings,
            "invariant": "Owning a subscription never marks an actor ready; every assignment is UNQUALIFIED."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propose role assignments for declared LLM subscriptions")
    parser.add_argument("--declare", required=True, help="comma-separated actors, e.g. claude,chatgpt,codex")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save-to", type=Path, help="Create a NEW proposal file; never overwrites")
    args = parser.parse_args(argv)
    try:
        actors = {a["id"]: a for a in load("actors.json")["actors"]}
        plan = build_plan(parse_declared(args.declare, actors))
        if args.save_to:
            save_exclusive(args.save_to, plan)
    except (ValueError, OSError, KeyError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print("OneCompany team proposal - NOT APPROVED, nothing enabled")
    for row in plan["assignments"]:
        print(f"  {row['role']:<20} -> {row['actor']:<22} [{row['status']}]" + (f"  ({row['note']})" if row["note"] else ""))
    for item in plan["excluded"]:
        print(f"  excluded: {item['actor']} ({item['cost_class']}): {item['reason']}")
    for warning in plan["warnings"]:
        print("WARNING: " + warning)
    print(plan["invariant"])
    print("Next: qualify each assigned actor: python onecompany.py qualify-worker --json (see docs/agent-setup/).")
    if args.save_to:
        print("Proposal exported to a new file: " + str(args.save_to))
    return 0


if __name__ == "__main__":
    sys.exit(main())
