#!/usr/bin/env python3
"""Trace-level liveness and hygiene invariants for L5 shadow/active runs."""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

TERMINAL_RUN_STATUSES = frozenset({"COMPLETE", "BLOCKED", "WAIT", "IDLE", "FAILED"})
NAMED_WAIT_PREFIXES = (
    "WAIT_",
    "CI_",
    "REVIEW_",
    "DEPENDENCY_",
    "PROVIDER_",
    "POST_MERGE_",
    "RECOVERY_",
    "OUTCOME_",
    "PLATFORM_",
)
LIMITS = {
    "ci_reruns": 2,
    "fix_iterations": 5,
    "review_rounds": 3,
    "lease_acquisitions": 12,
}


def check_liveness(
    events: Sequence[Mapping[str, Any]],
    *,
    max_stagnant_runs: int = 5,
) -> tuple[bool, tuple[str, ...]]:
    """Fail closed on malformed budgets, unbounded stagnation, or non-quiescence."""
    if type(max_stagnant_runs) is not int or max_stagnant_runs < 1:
        raise ValueError("MAX_STAGNANT_RUNS_INVALID")
    failures: list[str] = []
    stagnant: dict[tuple[str, str], int] = {}
    last_epoch: dict[tuple[str, str], str] = {}

    for event in events:
        repo = str(event.get("repo") or "")
        item = str(event.get("item_id") or "repo")
        key = (repo, item)
        status = event.get("status")
        status_valid = isinstance(status, str) and status in TERMINAL_RUN_STATUSES
        if not status_valid:
            failures.append("RUN_NOT_TERMINAL")

        budget = event.get("budget")
        if not isinstance(budget, Mapping):
            failures.append("BUDGET_EVIDENCE_INVALID")
        else:
            for name, limit in LIMITS.items():
                if name not in budget:
                    failures.append(f"BUDGET_MISSING_{name.upper()}")
                    continue
                value = budget[name]
                if type(value) is not int or value < 0 or value > limit:
                    failures.append(f"BUDGET_INVALID_{name.upper()}")

        stable_cycle = event.get("stable_cycle") is True
        if stable_cycle and "writes" not in event:
            failures.append("WRITE_COUNT_INVALID")
            writes = 0
        else:
            writes = event.get("writes", 0)
            if type(writes) is not int or writes < 0:
                failures.append("WRITE_COUNT_INVALID")
                writes = 0
        # A stabilized cycle may write only when a fresh external change is
        # positively evidenced. Missing/unknown evidence is never permission.
        if stable_cycle and writes != 0 and event.get("external_changes") is not True:
            failures.append("IDLE_NOT_QUIESCENT")

        # State/reason churn on an unchanged head/base is not substantive
        # progress. Bound the whole exact-head/base epoch so oscillation cannot
        # reset the stagnation budget indefinitely.
        epoch = json.dumps([event.get("head"), event.get("base")], sort_keys=True)
        reason = str(event.get("reason") or "")
        named_wait = status_valid and status == "WAIT" and (
            any(reason.startswith(prefix) for prefix in NAMED_WAIT_PREFIXES)
            or reason in {"LEASE_BUSY", "MERGED_UNVERIFIED"}
        )
        # Terminal success/idle, explicit parking, and named external waits are
        # bounded outcomes rather than controller stagnation. FAILED is not:
        # repeated failure or state oscillation on an unchanged head/base must
        # consume the stagnation budget and eventually fail closed.
        if status_valid and (status in {"COMPLETE", "IDLE"} or event.get("state") == "PARKED" or named_wait):
            stagnant[key] = 0
        elif last_epoch.get(key) == epoch:
            stagnant[key] = stagnant.get(key, 0) + 1
            if stagnant[key] > max_stagnant_runs:
                failures.append("UNBOUNDED_STAGNATION")
        else:
            stagnant[key] = 1
        last_epoch[key] = epoch

    return not failures, tuple(dict.fromkeys(failures))
