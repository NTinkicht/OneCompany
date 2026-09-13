#!/usr/bin/env python3
"""Simulate liveness-policy invariants without provider or GitHub calls."""
from __future__ import annotations

import sys

from onecompany_lib import CONTROL, load_json


def check(name: str, condition: bool) -> bool:
    print(("PASS" if condition else "FAIL") + ": " + name)
    return condition


def main() -> int:
    supervision = load_json(CONTROL / "supervision.json")
    safety = supervision.get("safety", {})
    chatgpt = supervision.get("chatgpt_tasks", {})
    results = []

    results.append(check("scheduler is supervisor, not implementer", safety.get("scheduler_is_supervisor_not_implementer") is True))
    results.append(check("live reconciliation precedes action", safety.get("must_reconcile_live_github_before_action") is True))
    results.append(check("stale suspicion does not prove failover", safety.get("must_verify_no_deterministic_job_progress_before_failover") is True))
    results.append(check("scheduled replicas cannot authorize duplicate streams", safety.get("never_create_duplicate_implementation_stream") is True))
    results.append(check("scheduled replicas cannot override budget", safety.get("never_override_budget_policy") is True))
    results.append(check("scheduled replicas cannot override human-only decisions", safety.get("never_override_human_only_decisions") is True))

    offsets = chatgpt.get("offset_minutes", [])
    results.append(check("staggered supervisor offsets are unique", len(offsets) == len(set(offsets))))
    if len(offsets) == 4:
        ordered = sorted(offsets)
        gaps = [ordered[i + 1] - ordered[i] for i in range(3)] + [ordered[0] + 60 - ordered[-1]]
        results.append(check("four hourly supervisors approximate 15-minute cadence", max(gaps) <= 16 and min(gaps) >= 14))

    results.append(check("safe foundation starts with supervision disabled", supervision.get("enabled") is False))
    results.append(check("safe foundation starts observe-only", supervision.get("mode") == "observe_only"))
    results.append(check("GitHub supervisor starts without failover authority", supervision.get("github_actions", {}).get("may_failover") is False))
    results.append(check("GitHub supervisor starts without merge authority", supervision.get("github_actions", {}).get("may_merge") is False))
    results.append(check("ChatGPT scheduled supervisors start without mutation authority", chatgpt.get("may_mutate") is False))

    failed = len([value for value in results if not value])
    print(f"\nSupervision simulation: {len(results)-failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
