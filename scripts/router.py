#!/usr/bin/env python3
"""Choose eligible actors by capability, budget, configuration, and authorship conflicts."""
from __future__ import annotations

import argparse
import json
import sys

from onecompany_lib import CONTROL, budget_allows, load_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", action="append", required=True, help="Required capability; repeatable")
    parser.add_argument("--exclude-author", action="append", default=[], help="Actor ID materially conflicted for independent gate")
    parser.add_argument("--for-independent-gate", action="store_true")
    args = parser.parse_args()

    actors_doc = load_json(CONTROL / "actors.json")
    budget = load_json(CONTROL / "budget.json")
    required = set(args.capability)
    excluded = set(args.exclude_author)

    eligible = []
    rejected = []
    for index, actor in enumerate(actors_doc.get("actors", [])):
        reasons = []
        actor_id = actor["id"]
        if not actor.get("enabled"):
            reasons.append("disabled")
        if not actor.get("configured"):
            reasons.append("not_configured")
        missing = sorted(required - set(actor.get("capabilities", [])))
        if missing:
            reasons.append("missing_capabilities:" + ",".join(missing))
        if not budget_allows(actor.get("cost_class", "UNKNOWN_COST"), budget):
            reasons.append("forbidden_by_budget")
        if args.for_independent_gate and actor_id in excluded:
            reasons.append("material_author_conflict")
        if args.for_independent_gate and actor.get("may_independently_gate_own_material_authorship"):
            reasons.append("self_gate_policy_conflict")

        if reasons:
            rejected.append({"actor": actor_id, "reasons": reasons})
        else:
            score = len(required & set(actor.get("capabilities", []))) * 100 - index
            eligible.append({"actor": actor_id, "score": score, "cost_class": actor.get("cost_class")})

    eligible.sort(key=lambda item: item["score"], reverse=True)
    print(json.dumps({"required": sorted(required), "eligible": eligible, "rejected": rejected}, indent=2))
    return 0 if eligible else 2


if __name__ == "__main__":
    sys.exit(main())
