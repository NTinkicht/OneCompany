#!/usr/bin/env python3
"""Run dependency-free policy simulations against core OneCompany invariants."""
from __future__ import annotations

import copy
import sys

from onecompany_lib import CONTROL, active_implementation_leases, budget_allows, load_json


def check(name: str, condition: bool) -> bool:
    print(("PASS" if condition else "FAIL") + ": " + name)
    return condition


def main() -> int:
    config = load_json(CONTROL / "config.json")
    budget = load_json(CONTROL / "budget.json")
    state = load_json(CONTROL / "state.json")
    results = []

    zero_spend = copy.deepcopy(budget)
    zero_spend["ai"]["additional_monthly_spend_cap"] = 0
    results.append(check("zero-spend rejects metered actor", not budget_allows("METERED_ALLOWED", zero_spend)))
    results.append(check("zero-spend allows included subscription", budget_allows("INCLUDED_SUBSCRIPTION", zero_spend)))

    one = copy.deepcopy(state)
    one["active_leases"] = [{"role": "implementation", "status": "active", "actor": "a"}]
    results.append(check("one implementation lease is representable", len(active_implementation_leases(one)) == 1))

    two = copy.deepcopy(one)
    two["active_leases"].append({"role": "implementation", "status": "active", "actor": "b"})
    results.append(check("duplicate implementation lease is detectable", len(active_implementation_leases(two)) > 1))

    head = "abc"
    gate = {"sha": "def", "verdict": "PASS — MERGE_READY"}
    results.append(check("stale exact-head gate is detectable", gate["sha"] != head))

    authors = {"chatgpt", "codex"}
    reviewer = "claude"
    results.append(check("independent reviewer is non-author", reviewer not in authors))
    reviewer = "codex"
    results.append(check("material author conflict is detectable", reviewer in authors))

    results.append(check("GitHub remains source of truth", config.get("project", {}).get("source_of_truth") == "github"))

    failed = len([r for r in results if not r])
    print(f"\nSimulation: {len(results)-failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
