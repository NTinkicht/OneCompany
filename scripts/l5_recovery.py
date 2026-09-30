#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from l5_state_machine import reduce_evidence

MAX_RETRIES = 3
SHA40 = re.compile(r"^[0-9a-f]{40}$")
RECOVERY_ACTIONS = {
    "START_CANONICAL_STREAM", "RECONCILE_CANONICAL_PR", "CONTINUE_IMPLEMENTATION",
    "RUN_OR_RECONCILE_EXACT_HEAD_CI", "RECONCILE_EXACT_HEAD_CI_EVIDENCE", "REMEDIATE_SAME_PR_CI",
    "DISPATCH_ELIGIBLE_NONAUTHOR_REVIEW", "FAILOVER_TO_ELIGIBLE_NONAUTHOR_REVIEWER",
    "RECONCILE_EXACT_HEAD_REVIEW_EVIDENCE", "RECONCILE_REVIEWER_IDENTITY", "RECONCILE_MATERIAL_AUTHORSHIP",
    "REMEDIATE_SAME_PR_REVIEW", "RECONCILE_MERGEABILITY", "VERIFY_MERGED_RESULT",
    "RECONCILE_VERIFIED_MERGE_EVIDENCE", "RECONCILE_POST_MERGE_STREAM_STATE", "RECONCILE_HEAD_BASE",
    "RECONCILE_EXACT_REFS",
}
RETRY_SCOPES = {
    "START_CANONICAL_STREAM":"STREAM", "RECONCILE_CANONICAL_PR":"STREAM", "CONTINUE_IMPLEMENTATION":"STREAM",
    "RECONCILE_HEAD_BASE":"STREAM", "RECONCILE_EXACT_REFS":"STREAM",
    "RUN_OR_RECONCILE_EXACT_HEAD_CI":"CI", "RECONCILE_EXACT_HEAD_CI_EVIDENCE":"CI", "REMEDIATE_SAME_PR_CI":"CI",
    "DISPATCH_ELIGIBLE_NONAUTHOR_REVIEW":"REVIEW", "FAILOVER_TO_ELIGIBLE_NONAUTHOR_REVIEWER":"REVIEW",
    "RECONCILE_EXACT_HEAD_REVIEW_EVIDENCE":"REVIEW", "RECONCILE_REVIEWER_IDENTITY":"REVIEW",
    "RECONCILE_MATERIAL_AUTHORSHIP":"REVIEW", "REMEDIATE_SAME_PR_REVIEW":"REVIEW",
    "RECONCILE_MERGEABILITY":"MERGE_READY", "VERIFY_MERGED_RESULT":"VERIFY",
    "RECONCILE_VERIFIED_MERGE_EVIDENCE":"VERIFY", "RECONCILE_POST_MERGE_STREAM_STATE":"VERIFY",
}
KNOWN_RETRY_SCOPES = frozenset(RETRY_SCOPES.values())


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"L5_RECOVERY_{name.upper()}_INVALID")
    return value.strip()


def _required_bool(row: dict[str, Any], key: str) -> bool:
    value = row.get(key)
    if type(value) is not bool:
        raise ValueError(f"L5_RECOVERY_{key.upper()}_UNKNOWN")
    return value


def _retry_state(snapshot: dict[str, Any], action: str) -> tuple[int, str | None]:
    count = snapshot.get("retry_count")
    if type(count) is not int or count < 0:
        raise ValueError("L5_RECOVERY_RETRY_COUNT_INVALID")
    persisted = snapshot.get("retry_action")
    if persisted is not None and (not isinstance(persisted, str) or not persisted.strip()):
        raise ValueError("L5_RECOVERY_RETRY_ACTION_INVALID")
    if count > 0 and persisted is None:
        raise ValueError("L5_RECOVERY_RETRY_ACTION_REQUIRED")
    normalized = persisted.strip() if isinstance(persisted, str) else None
    if normalized is not None and normalized not in KNOWN_RETRY_SCOPES:
        raise ValueError("L5_RECOVERY_RETRY_ACTION_UNKNOWN")
    current = RETRY_SCOPES.get(action)
    if current is None:
        return count, normalized
    return (count if normalized == current else 0), normalized


def _event_key(snapshot: dict[str, Any]) -> str:
    material = {
        "repository": snapshot.get("repository"), "issue": snapshot.get("issue"),
        "canonical_pr": snapshot.get("canonical_pr"), "head_sha": snapshot.get("head_sha"),
        "base_sha": snapshot.get("base_sha"), "event_id": _required_text(snapshot.get("event_id"), "event_id"),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _normalized_sha(value: Any) -> str | None:
    return value if isinstance(value, str) and SHA40.fullmatch(value) else None


def _normalized_pr(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def _eligible_ready_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = snapshot.get("ready_candidates")
    if not isinstance(rows, list):
        raise ValueError("L5_RECOVERY_READY_CANDIDATES_INVALID")
    eligible, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("L5_RECOVERY_READY_CANDIDATE_INVALID")
        issue = row.get("issue")
        if type(issue) is not int or issue < 1 or issue in seen:
            raise ValueError("L5_RECOVERY_READY_CANDIDATE_ID_INVALID")
        seen.add(issue)
        if _required_bool(row,"ready") and not _required_bool(row,"blocked") and not _required_bool(row,"human_only") and _required_bool(row,"conflict_safe"):
            eligible.append(row)
    return sorted(eligible, key=lambda row: row["issue"])


def plan_recovery(snapshot: dict[str, Any], *, prior_event_keys: set[str] | None = None) -> dict[str, Any]:
    """Plan one idempotent L4.8 recovery action without mutating GitHub."""
    if not isinstance(snapshot, dict):
        raise ValueError("L5_RECOVERY_SNAPSHOT_INVALID")
    event_key = _event_key(snapshot)
    if event_key in (prior_event_keys or set()):
        return {"status":"REPLAY_NOOP","event_key":event_key,"mutation_allowed":False,"next_action":"NONE_ALREADY_RECORDED"}
    state = reduce_evidence(snapshot); action = state["next_action"]
    count, persisted = _retry_state(snapshot, action); scope = RETRY_SCOPES.get(action)
    result = {
        "status":"PLANNED","event_key":event_key,"repository":state["repository"],"issue":state["issue"],
        "canonical_pr":state["canonical_pr"],"state":state["state"],"next_action":action,"retry_count":count,
        "retry_action":scope if action in RECOVERY_ACTIONS else persisted,"mutation_allowed":False,
    }
    if action in {"EMERGENCY_STOP_HOLD","HUMAN_OR_POLICY_BLOCKED","DUPLICATE_STREAM_RECONCILIATION_REQUIRED","CANONICAL_STREAM_MISMATCH"}:
        result["status"]="BLOCKED"; return result
    if action == "REPLENISH_NEXT_READY_WU":
        candidates = _eligible_ready_candidates(snapshot)
        if not candidates:
            result.update(status="IDLE",next_action="IDLE_NO_CONFLICT_SAFE_READY_WORK",retry_count=0,retry_action=None); return result
        result.update(next_action="PLAN_REPLENISH_READY_WU",selected_issue=candidates[0]["issue"],retry_count=0,retry_action=None); return result
    if action in RECOVERY_ACTIONS:
        if count >= MAX_RETRIES:
            result.update(status="BLOCKED",next_action="RETRY_BUDGET_EXHAUSTED"); return result
        result["retry_count_after"] = count + 1; result["retry_action_after"] = scope; return result
    if action == "AWAIT_AUTHORIZED_EXPECTED_HEAD_MERGE":
        result.update(status="READY",retry_count=0,retry_action=None); return result
    raise ValueError(f"L5_RECOVERY_UNHANDLED_ACTION:{action}")


def journal_record(snapshot: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_key":plan["event_key"],"repository":plan.get("repository",snapshot.get("repository")),
        "issue":plan.get("issue",snapshot.get("issue")),"canonical_pr":_normalized_pr(plan.get("canonical_pr",snapshot.get("canonical_pr"))),
        "head_sha":_normalized_sha(snapshot.get("head_sha")),"base_sha":_normalized_sha(snapshot.get("base_sha")),
        "status":plan["status"],"next_action":plan["next_action"],"retry_count":plan.get("retry_count",0),
        "retry_action":plan.get("retry_action"),"retry_count_after":plan.get("retry_count_after"),
        "retry_action_after":plan.get("retry_action_after"),"selected_issue":plan.get("selected_issue"),"mutation_allowed":False,
    }


def selftest() -> None:
    h,b="a"*40,"b"*40
    s={"repository":"NTinkicht/OneCompany","issue":251,"canonical_pr":252,"active_prs":[252],"head_sha":h,"base_sha":b,
       "head_current":True,"base_current":True,"implementation_complete":True,"emergency_stop":False,"human_only":False,
       "blocked":False,"merged":False,"verified":False,"verified_head_sha":None,"verified_base_sha":None,"ci":"FAILURE",
       "ci_head_sha":h,"ci_base_sha":b,"review":"UNKNOWN","review_head_sha":None,"review_base_sha":None,"reviewer_actor":None,
       "material_authors":["chatgpt"],"material_authors_head_sha":h,"review_eligible":False,"unresolved_threads":False,
       "mergeable":True,"retry_count":0,"retry_action":None,"event_id":"evt-1","ready_candidates":[]}
    p=plan_recovery(s); assert p["next_action"]=="REMEDIATE_SAME_PR_CI" and p["retry_action_after"]=="CI"
    assert plan_recovery(s,prior_event_keys={p["event_key"]})["status"]=="REPLAY_NOOP"
    assert plan_recovery({**s,"retry_count":MAX_RETRIES,"retry_action":"CI"})["next_action"]=="RETRY_BUDGET_EXHAUSTED"
    hold=plan_recovery({**s,"retry_count":2,"retry_action":"CI","emergency_stop":True})
    assert hold["retry_count"]==2 and hold["retry_action"]=="CI"
    print("l5_recovery selftest PASS")


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--selftest",action="store_true"); parser.add_argument("--input",type=Path); args=parser.parse_args()
    if args.selftest: selftest(); return 0
    if args.input is None: raise SystemExit("--input is required unless --selftest is used")
    snapshot=json.loads(args.input.read_text(encoding="utf-8")); plan=plan_recovery(snapshot)
    print(json.dumps({"plan":plan,"journal":journal_record(snapshot,plan)},indent=2,sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())
