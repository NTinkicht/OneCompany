#!/usr/bin/env python3
"""Deterministic read-only L5 lifecycle certification fault drill."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from l5_recovery import MAX_RETRIES, plan_recovery


def base(event_id: str = "cert-0") -> dict[str, Any]:
    h, b = "a" * 40, "b" * 40
    return {
        "repository": "NTinkicht/OneCompany",
        "issue": 260,
        "canonical_pr": 261,
        "active_prs": [261],
        "head_sha": h,
        "base_sha": b,
        "head_current": True,
        "base_current": True,
        "implementation_complete": True,
        "emergency_stop": False,
        "human_only": False,
        "blocked": False,
        "merged": False,
        "verified": False,
        "verified_head_sha": None,
        "verified_base_sha": None,
        "ci": "SUCCESS",
        "ci_head_sha": h,
        "ci_base_sha": b,
        "review": "PASS",
        "review_head_sha": h,
        "review_base_sha": b,
        "reviewer_actor": "mistral-vibe",
        "material_authors": ["chatgpt"],
        "material_authors_head_sha": h,
        "review_eligible": True,
        "unresolved_threads": False,
        "mergeable": True,
        "retry_count": 0,
        "retry_action": None,
        "event_id": event_id,
        "ready_candidates": [],
    }


def _case(name: str, snapshot: dict[str, Any], expected: str,
          *, prior: set[str] | None = None) -> dict[str, Any]:
    plan = plan_recovery(snapshot, prior_event_keys=prior)
    if plan["next_action"] != expected:
        raise AssertionError(f"{name}: expected {expected}, got {plan['next_action']}")
    if plan.get("mutation_allowed") is not False:
        raise AssertionError(f"{name}: certification observed mutation authority")
    return {"name": name, "status": plan["status"], "next_action": plan["next_action"]}


def certify() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    rows.append(_case("merge-ready-read-only", base("c1"), "AWAIT_AUTHORIZED_EXPECTED_HEAD_MERGE"))
    red = {**base("c2"), "ci": "FAILURE"}
    rows.append(_case("ci-red-same-stream", red, "REMEDIATE_SAME_PR_CI"))
    transient = {**base("c3"), "ci": "PENDING", "retry_count": 2, "retry_action": "CI"}
    transient_plan = plan_recovery(transient)
    if transient_plan.get("retry_count_after") != 3:
        raise AssertionError("ci transient did not preserve phase retry budget")
    rows.append({"name": "ci-transient-budget", "status": transient_plan["status"], "next_action": transient_plan["next_action"]})
    rows.append(_case("retry-exhaustion", {**red, "event_id": "c4", "retry_count": MAX_RETRIES, "retry_action": "CI"}, "RETRY_BUDGET_EXHAUSTED"))
    rows.append(_case("reviewer-outage", {**base("c5"), "review": "OUTAGE"}, "FAILOVER_TO_ELIGIBLE_NONAUTHOR_REVIEWER"))
    rows.append(_case("self-review-rejected", {**base("c6"), "reviewer_actor": "chatgpt"}, "DISPATCH_ELIGIBLE_NONAUTHOR_REVIEW"))
    rows.append(_case("duplicate-stream", {**base("c7"), "active_prs": [261, 262]}, "DUPLICATE_STREAM_RECONCILIATION_REQUIRED"))
    rows.append(_case("stale-head", {**base("c8"), "head_current": False}, "RECONCILE_HEAD_BASE"))
    rows.append(_case("moved-base", {**base("c9"), "base_current": False}, "RECONCILE_HEAD_BASE"))
    rows.append(_case("emergency-stop", {**base("c10"), "emergency_stop": True}, "EMERGENCY_STOP_HOLD"))
    rows.append(_case("human-only", {**base("c11"), "human_only": True}, "HUMAN_OR_POLICY_BLOCKED"))
    rows.append(_case("malformed-refs", {**base("c12"), "head_sha": "broken"}, "RECONCILE_EXACT_REFS"))
    merged = {**base("c13"), "active_prs": [], "merged": True, "verified": False,
              "retry_count": MAX_RETRIES, "retry_action": "CI"}
    verify_plan = plan_recovery(merged)
    if verify_plan["next_action"] != "VERIFY_MERGED_RESULT" or verify_plan.get("retry_action_after") != "VERIFY" or verify_plan.get("retry_count") != 0:
        raise AssertionError("post-merge verification did not reset prior phase budget")
    rows.append({"name": "merged-unverified", "status": verify_plan["status"], "next_action": verify_plan["next_action"]})
    rows.append(_case("verified-ref-mismatch", {**merged, "event_id": "c14", "verified": True}, "RECONCILE_VERIFIED_MERGE_EVIDENCE"))
    complete = {**base("c15"), "active_prs": [], "merged": True, "verified": True,
                "verified_head_sha": "a" * 40, "verified_base_sha": "b" * 40}
    rows.append(_case("empty-ready-queue", complete, "IDLE_NO_CONFLICT_SAFE_READY_WORK"))
    candidates = [
        {"issue": 300, "ready": True, "blocked": False, "human_only": False, "conflict_safe": False},
        {"issue": 301, "ready": True, "blocked": False, "human_only": False, "conflict_safe": True},
    ]
    select_plan = plan_recovery({**complete, "event_id": "c16", "ready_candidates": candidates})
    if select_plan["next_action"] != "PLAN_REPLENISH_READY_WU" or select_plan.get("selected_issue") != 301 or select_plan.get("mutation_allowed") is not False:
        raise AssertionError("conflict-safe replenishment selection failed")
    rows.append({"name": "conflict-safe-selection", "status": select_plan["status"], "next_action": select_plan["next_action"]})
    replay_source = {**red, "event_id": "c17"}
    first = plan_recovery(replay_source)
    rows.append(_case("lost-response-replay", replay_source, "NONE_ALREADY_RECORDED", prior={first["event_key"]}))
    hold = plan_recovery({**red, "event_id": "c18", "retry_count": 2, "retry_action": "CI", "emergency_stop": True})
    if hold.get("retry_count") != 2 or hold.get("retry_action") != "CI":
        raise AssertionError("hold did not preserve retry state")
    rows.append({"name": "hold-preserves-budget", "status": hold["status"], "next_action": hold["next_action"]})
    payload = {"version": 1, "repository": "NTinkicht/OneCompany", "certified": True, "mutation_allowed": False, "cases": rows}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["report_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload


def main() -> int:
    report = certify()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
