#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

STATE_ORDER = [
    "SELECTED",
    "IMPLEMENTING",
    "TESTING",
    "REVIEWING",
    "REMEDIATING",
    "MERGE_READY",
    "MERGED",
    "VERIFYING",
    "COMPLETE",
]
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _required_text(evidence: dict, key: str) -> str:
    value = evidence.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"L5_STATE_MISSING_{key.upper()}")
    return value.strip()


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and bool(SHA40.fullmatch(value))


def reduce_evidence(evidence: dict) -> dict:
    """Reduce a bounded evidence snapshot to one state and one safe next action."""
    if not isinstance(evidence, dict):
        raise ValueError("L5_STATE_EVIDENCE_INVALID")

    repository = _required_text(evidence, "repository")
    issue = evidence.get("issue")
    if type(issue) is not int or issue < 1:
        raise ValueError("L5_STATE_ISSUE_INVALID")

    canonical_pr = evidence.get("canonical_pr")
    active_prs = evidence.get("active_prs", [])
    if not isinstance(active_prs, list) or not all(type(value) is int and value > 0 for value in active_prs):
        raise ValueError("L5_STATE_ACTIVE_PRS_INVALID")
    if len(set(active_prs)) != len(active_prs):
        raise ValueError("L5_STATE_ACTIVE_PRS_DUPLICATE")

    result = {
        "repository": repository,
        "issue": issue,
        "canonical_pr": canonical_pr,
        "state": "SELECTED",
        "next_action": "START_CANONICAL_STREAM",
        "mutation_allowed": False,
    }

    if evidence.get("emergency_stop") is True:
        result.update(state="SELECTED", next_action="EMERGENCY_STOP_HOLD")
        return result
    if evidence.get("human_only") is True or evidence.get("blocked") is True:
        result.update(state="SELECTED", next_action="HUMAN_OR_POLICY_BLOCKED")
        return result
    if len(active_prs) > 1:
        result.update(state="SELECTED", next_action="DUPLICATE_STREAM_RECONCILIATION_REQUIRED")
        return result

    if canonical_pr is None:
        if active_prs:
            result.update(next_action="RECONCILE_CANONICAL_PR")
        return result
    if type(canonical_pr) is not int or canonical_pr < 1:
        raise ValueError("L5_STATE_CANONICAL_PR_INVALID")
    if active_prs and active_prs != [canonical_pr]:
        result.update(next_action="CANONICAL_STREAM_MISMATCH")
        return result

    head = evidence.get("head_sha")
    base = evidence.get("base_sha")
    if not _valid_sha(head) or not _valid_sha(base):
        result.update(state="IMPLEMENTING", next_action="RECONCILE_EXACT_REFS")
        return result
    if evidence.get("head_current") is False or evidence.get("base_current") is False:
        result.update(state="IMPLEMENTING", next_action="RECONCILE_HEAD_BASE")
        return result

    if evidence.get("merged") is True:
        result["state"] = "COMPLETE" if evidence.get("verified") is True else "VERIFYING"
        result["next_action"] = "REPLENISH_NEXT_READY_WU" if result["state"] == "COMPLETE" else "VERIFY_MERGED_RESULT"
        return result

    if evidence.get("implementation_complete") is not True:
        result.update(state="IMPLEMENTING", next_action="CONTINUE_IMPLEMENTATION")
        return result

    ci = evidence.get("ci", "UNKNOWN")
    if ci in {"FAILURE", "CANCELLED", "TIMED_OUT"}:
        result.update(state="REMEDIATING", next_action="REMEDIATE_SAME_PR_CI")
        return result
    if ci != "SUCCESS":
        result.update(state="TESTING", next_action="RUN_OR_RECONCILE_EXACT_HEAD_CI")
        return result

    review = evidence.get("review", "UNKNOWN")
    if review in {"CHANGES_REQUESTED", "FINDINGS"} or evidence.get("unresolved_threads") is True:
        result.update(state="REMEDIATING", next_action="REMEDIATE_SAME_PR_REVIEW")
        return result
    if review == "OUTAGE":
        result.update(state="REVIEWING", next_action="FAILOVER_TO_ELIGIBLE_NONAUTHOR_REVIEWER")
        return result
    if review != "PASS":
        result.update(state="REVIEWING", next_action="DISPATCH_ELIGIBLE_NONAUTHOR_REVIEW")
        return result

    if evidence.get("mergeable") is not True:
        result.update(state="REMEDIATING", next_action="RECONCILE_MERGEABILITY")
        return result

    result.update(state="MERGE_READY", next_action="AWAIT_AUTHORIZED_EXPECTED_HEAD_MERGE")
    return result


def selftest() -> None:
    base = {
        "repository": "NTinkicht/OneCompany",
        "issue": 249,
        "canonical_pr": 250,
        "active_prs": [250],
        "head_sha": "a" * 40,
        "base_sha": "b" * 40,
        "head_current": True,
        "base_current": True,
        "implementation_complete": True,
    }
    assert reduce_evidence({**base, "ci": "SUCCESS", "review": "PASS", "mergeable": True})["state"] == "MERGE_READY"
    assert reduce_evidence({**base, "ci": "FAILURE"})["next_action"] == "REMEDIATE_SAME_PR_CI"
    assert reduce_evidence({**base, "ci": "SUCCESS", "review": "OUTAGE"})["next_action"] == "FAILOVER_TO_ELIGIBLE_NONAUTHOR_REVIEWER"
    assert reduce_evidence({**base, "head_current": False})["next_action"] == "RECONCILE_HEAD_BASE"
    assert reduce_evidence({**base, "active_prs": [250, 251]})["next_action"] == "DUPLICATE_STREAM_RECONCILIATION_REQUIRED"
    assert reduce_evidence({**base, "merged": True, "verified": False})["state"] == "VERIFYING"
    assert reduce_evidence({**base, "merged": True, "verified": True})["next_action"] == "REPLENISH_NEXT_READY_WU"
    assert reduce_evidence({**base, "emergency_stop": True})["next_action"] == "EMERGENCY_STOP_HOLD"
    print("l5_state_machine selftest PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if args.input is None:
        raise SystemExit("--input is required unless --selftest is used")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(reduce_evidence(payload), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
