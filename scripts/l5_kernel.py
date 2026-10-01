#!/usr/bin/env python3
"""Claude hostile-design L5 coordination kernel.

This module is credential-free. It evaluates structured evidence, coordinates
CAS leases/intents, and never treats LLM prose as gate evidence.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
import json, re, uuid
from typing import Any, Mapping, Protocol

SHA40 = re.compile(r"^[0-9a-fA-F]{40}$")
DANGEROUS = frozenset({"push", "update_branch", "merge", "enqueue", "revert"})
HARMLESS = frozenset({"label", "comment", "review_request", "ci_rerun"})
MAX_CI_RERUNS = 2
MAX_FIX_ITERATIONS = 5
MAX_REVIEW_ROUNDS = 3
MAX_LEASES = 12

class RepoMode(str, Enum):
    NORMAL="NORMAL"; MERGE_LOCKED="MERGE_LOCKED"; MAIN_BROKEN="MAIN_BROKEN"; MAIN_BROKEN_ENV="MAIN_BROKEN_ENV"
    AUTOMATION_DEGRADED="AUTOMATION_DEGRADED"; PROVIDER_THROTTLED="PROVIDER_THROTTLED"; GOVERNANCE_DRIFT="GOVERNANCE_DRIFT"
    SECURITY_INTEGRITY_FAILURE="SECURITY_INTEGRITY_FAILURE"; CONTROLLER_INTEGRITY="CONTROLLER_INTEGRITY"; HALTED="HALTED"
    ARCHIVED_PERMISSION_LOST="ARCHIVED_PERMISSION_LOST"

HUMAN_CLEAR_ONLY = frozenset({RepoMode.HALTED, RepoMode.CONTROLLER_INTEGRITY, RepoMode.SECURITY_INTEGRITY_FAILURE, RepoMode.GOVERNANCE_DRIFT})

class ItemState(str, Enum):
    GOVERNANCE_CHANGE="GOVERNANCE_CHANGE"; WAIT_CI="WAIT_CI"; CI_MISSING="CI_MISSING"; CI_RED_INFRA="CI_RED_INFRA"
    CI_RED_DETERMINISTIC="CI_RED_DETERMINISTIC"; BEHIND_BASE="BEHIND_BASE"; CI_GREEN_UNREVIEWED="CI_GREEN_UNREVIEWED"
    FINDINGS_OPEN="FINDINGS_OPEN"; DISPUTED_FINDING="DISPUTED_FINDING"; BLOCK_HUMAN="BLOCK_HUMAN"; WAIT_DEPENDENCY="WAIT_DEPENDENCY"
    MERGE_ELIGIBLE="MERGE_ELIGIBLE"; MERGE_QUEUED="MERGE_QUEUED"; MERGE_OUTCOME_UNKNOWN="MERGE_OUTCOME_UNKNOWN"
    MERGED_UNVERIFIED="MERGED_UNVERIFIED"; MERGED_VERIFIED="MERGED_VERIFIED"; MAIN_BROKEN="MAIN_BROKEN"; REVERT_PENDING="REVERT_PENDING"
    SUPERSEDED="SUPERSEDED"; PARKED="PARKED"; WAIT_PROVIDER="WAIT_PROVIDER"; IMPLEMENT="IMPLEMENT"; IDLE="IDLE"

@dataclass(frozen=True)
class Observation:
    head: str
    base: str
    wu_body_hash: str = ""
    pr_updated_at: str = ""

@dataclass(frozen=True)
class Intent:
    op_id: str
    idem_key: str
    operation: str
    expected_head: str
    expected_base: str
    epoch: int
    state: str = "PENDING"

@dataclass(frozen=True)
class Lease:
    key: str
    holder: str
    epoch: int
    observed: Observation
    acquired_at: float
    expires_at: float
    version: int
    intent: Intent | None = None

@dataclass(frozen=True)
class Budget:
    ci_reruns: int = 0
    fix_iterations: int = 0
    review_rounds: int = 0
    lease_acquisitions: int = 0
    def exhausted(self) -> bool:
        return self.ci_reruns >= MAX_CI_RERUNS or self.fix_iterations >= MAX_FIX_ITERATIONS or self.review_rounds >= MAX_REVIEW_ROUNDS or self.lease_acquisitions >= MAX_LEASES

class CASStore(Protocol):
    def read(self, key: str) -> Lease | None: ...
    def cas(self, key: str, expected_version: int | None, value: Lease) -> bool: ...
    def read_repo_mode(self, repo_id: str) -> tuple[RepoMode, int | None]: ...
    def cas_repo_mode(self, repo_id: str, expected_version: int | None, mode: RepoMode) -> bool: ...

class MemoryCASStore:
    """Test only. Production authority is the GitHub-backed ledger."""
    def __init__(self):
        self.leases: dict[str, Lease] = {}
        self.modes: dict[str, tuple[RepoMode, int]] = {}
    def read(self, key): return self.leases.get(key)
    def cas(self, key, expected_version, value):
        cur = self.leases.get(key); actual = None if cur is None else cur.version
        if actual != expected_version: return False
        self.leases[key] = value; return True
    def read_repo_mode(self, repo_id): return self.modes.get(repo_id, (RepoMode.NORMAL, None))
    def cas_repo_mode(self, repo_id, expected_version, mode):
        cur = self.modes.get(repo_id); actual = None if cur is None else cur[1]
        if actual != expected_version: return False
        self.modes[repo_id] = (mode, 1 if cur is None else cur[1] + 1); return True

def new_run_id() -> str: return str(uuid.uuid4())
def idem_key(repo_id: str, item: str, head: str, operation: str) -> str:
    return sha256(json.dumps([repo_id, item, head, operation], separators=(",", ":")).encode()).hexdigest()
def lease_key(repo_id: str, item_kind: str, item_id: str, op_class: str) -> str: return f"{repo_id}:{item_kind}:{item_id}:{op_class}"
def repo_merge_lock_key(repo_id: str) -> str: return lease_key(repo_id, "repo", repo_id, "REPO_MERGE_LOCK")
def capacity_slot_key(repo_id: str, slot: int) -> str:
    if type(slot) is not int or slot < 1: raise ValueError("CAPACITY_SLOT_INVALID")
    return lease_key(repo_id, "capacity", str(slot), f"CAPACITY_SLOT_{slot}")

def acquire(store, key, holder, observed, *, now_srv, ttl=300):
    cur = store.read(key)
    if cur and cur.expires_at > now_srv: return None
    if cur and cur.intent and cur.intent.state == "PENDING": return None
    epoch = 1 if cur is None else cur.epoch + 1; version = 1 if cur is None else cur.version + 1
    nxt = Lease(key, holder, epoch, observed, now_srv, now_srv + ttl, version)
    return nxt if store.cas(key, None if cur is None else cur.version, nxt) else None

def renew(store, lease, *, now_srv, ttl=300):
    cur = store.read(lease.key)
    if cur != lease or cur.holder != lease.holder or cur.epoch != lease.epoch: return None
    nxt = replace(lease, expires_at=now_srv + ttl, version=lease.version + 1)
    return nxt if store.cas(lease.key, lease.version, nxt) else None

def attach_intent(store, lease, repo_id, item, operation):
    cur = store.read(lease.key)
    if cur != lease or cur.holder != lease.holder or cur.epoch != lease.epoch or operation not in DANGEROUS | HARMLESS: return None
    it = Intent(str(uuid.uuid4()), idem_key(repo_id, item, lease.observed.head, operation), operation, lease.observed.head, lease.observed.base, lease.epoch)
    nxt = replace(lease, intent=it, version=lease.version + 1)
    return nxt if store.cas(lease.key, lease.version, nxt) else None

def resolve_intent(store, lease, state):
    if state not in {"DONE", "ABORTED"}: raise ValueError("INTENT_RESOLUTION_INVALID")
    cur = store.read(lease.key)
    if cur != lease or cur.intent is None or cur.intent.state != "PENDING": return None
    nxt = replace(cur, intent=replace(cur.intent, state=state), version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None

def release(store, lease, *, now_srv, intent_state="DONE"):
    cur = store.read(lease.key)
    if cur is None or cur.holder != lease.holder or cur.epoch != lease.epoch: return None
    it = cur.intent
    if it is not None and it.state == "PENDING":
        if intent_state not in {"DONE", "ABORTED"}: raise ValueError("INTENT_RELEASE_STATE_INVALID")
        it = replace(it, state=intent_state)
    nxt = replace(cur, intent=it, expires_at=now_srv, version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None

def intent_recovery(lease, detection_result):
    if lease.intent is None or lease.intent.state != "PENDING": return "NO_PENDING_INTENT"
    if detection_result == "APPLIED": return "RESOLVE_DONE"
    if detection_result == "NOT_APPLIED": return "RESOLVE_ABORTED"
    if detection_result == "UNKNOWN": return "READBACK_REQUIRED"
    raise ValueError("DETECTION_RESULT_INVALID")

def fence_ok(store, repo_id, lease, observed_now, *, now_srv, max_write_latency=30, skew_margin=30):
    cur = store.read(lease.key)
    if cur is None: return False, "LEASE_MISSING"
    if cur.holder != lease.holder or cur.epoch != lease.epoch or cur.version != lease.version: return False, "LEASE_LOST"
    if now_srv + max_write_latency + skew_margin >= cur.expires_at: return False, "LEASE_TOO_CLOSE_TO_EXPIRY"
    if cur.observed != observed_now: return False, "OBSERVATION_CHANGED"
    if cur.intent is None or cur.intent.state != "PENDING" or cur.intent.epoch != cur.epoch: return False, "INTENT_INVALID"
    mode, _ = store.read_repo_mode(repo_id)
    if mode != RepoMode.NORMAL and cur.intent.operation not in {"revert", "comment"}: return False, f"REPO_MODE_{mode.value}"
    if cur.intent.operation not in DANGEROUS | HARMLESS: return False, "OPERATION_NOT_ALLOWLISTED"
    return True, "OK"

def governance_mode(s: Mapping[str, Any]) -> RepoMode:
    if s.get("halted") is True: return RepoMode.HALTED
    if s.get("controller_integrity_failure") is True: return RepoMode.CONTROLLER_INTEGRITY
    if s.get("security_integrity_failure") is True: return RepoMode.SECURITY_INTEGRITY_FAILURE
    if s.get("ledger_reachable") is False: return RepoMode.AUTOMATION_DEGRADED
    if not all(s.get(k) is True for k in ("platform_enforcement_ok", "live_rules_at_least_pinned", "rulesets_or_protection_active", "required_check_sources_pinned")) or s.get("controller_admin") is True or s.get("controller_bypass") is True: return RepoMode.GOVERNANCE_DRIFT
    if s.get("main_broken") is True: return RepoMode.MAIN_BROKEN
    if s.get("main_broken_env") is True: return RepoMode.MAIN_BROKEN_ENV
    if s.get("automation_degraded") is True: return RepoMode.AUTOMATION_DEGRADED
    if s.get("provider_throttled") is True: return RepoMode.PROVIDER_THROTTLED
    if s.get("merge_locked") is True: return RepoMode.MERGE_LOCKED
    if s.get("archived_or_permission_lost") is True: return RepoMode.ARCHIVED_PERMISSION_LOST
    return RepoMode.NORMAL

def _sha(v): return isinstance(v, str) and bool(SHA40.fullmatch(v))
def _source_key(v):
    if not isinstance(v, Mapping): return None
    app = v.get("app_id"); path = v.get("workflow_path")
    if not isinstance(app, (str, int)) or not isinstance(path, str) or not path: return None
    return str(app), path

def _checks_ok(rows, head, base, expected_sources):
    if not isinstance(rows, list) or not isinstance(expected_sources, list) or not expected_sources: return False
    expected = [_source_key(x) for x in expected_sources]
    if any(x is None for x in expected) or len(set(expected)) != len(expected): return False
    by_source = {}
    for row in rows:
        key = _source_key(row)
        if key is not None: by_source.setdefault(key, []).append(row)
    for key in expected:
        candidates = by_source.get(key, [])
        if len(candidates) != 1: return False
        r = candidates[0]
        if r.get("head_sha") != head: return False
        if r.get("tested_base_sha") != base and r.get("merge_queue") is not True: return False
        if r.get("latest_attempt") is not True or r.get("conclusion") != "success": return False
        if r.get("assertion_failure_any_attempt") is True: return False
    return True

def _review_ok(r, head, base):
    if not isinstance(r, Mapping): return False
    if r.get("state") != "APPROVED" or r.get("commit_id") != head or r.get("base_sha") != base: return False
    if r.get("complete") is not True or r.get("skipped") is True or r.get("covers_full_diff") is not True: return False
    reviewer = r.get("author"); authors = r.get("material_authors"); ctrls = r.get("controller_identities")
    if not isinstance(reviewer, str) or not reviewer or not isinstance(authors, list) or not isinstance(ctrls, list): return False
    norm = reviewer.strip().lower()
    if norm in {str(x).strip().lower() for x in authors + ctrls}: return False
    return r.get("designated_independent") is True

TRUE_FIELDS = ("merge_lock_owned", "fence_ok", "pr_open", "same_repo", "base_ref_expected", "head_ref_matches_api", "base_currency_ok", "mergeable", "mergeable_state_clean", "live_rules_at_least_pinned", "rulesets_or_protection_active", "files_fully_enumerated", "diff_within_limit", "adapter_hash_ok", "controller_hash_ok", "code_scanning_present", "review_decision_ok", "findings_confirmed_closed", "thread_resolution_policy_ok", "human_gate_checks_ok", "dependencies_verified", "required_check_sources_pinned", "credential_isolation_ok", "secret_hygiene_ok")
FALSE_FIELDS = ("global_halted", "repo_halted", "unresolved_other_intent", "pr_draft", "pr_locked", "fork_pr", "controller_admin", "controller_bypass", "governed_path_touched", "test_weakening", "new_security_alert", "secret_finding", "later_changes_requested", "unresolved_required_threads", "human_hold")

def merge_ok(s: Mapping[str, Any]):
    fail = []; head = s.get("head_sha"); base = s.get("base_sha")
    if not _sha(head): fail.append("HEAD_UNKNOWN")
    if not _sha(base): fail.append("BASE_UNKNOWN")
    if s.get("repo_mode") != RepoMode.NORMAL.value: fail.append("REPO_MODE_NOT_NORMAL")
    for k in TRUE_FIELDS:
        if s.get(k) is not True: fail.append(k.upper() + "_NOT_TRUE")
    for k in FALSE_FIELDS:
        if s.get(k) is not False: fail.append(k.upper() + "_NOT_FALSE")
    if _sha(head) and s.get("expected_head_sha") != head: fail.append("EXPECTED_HEAD_MISMATCH")
    if _sha(base) and s.get("expected_base_sha") != base: fail.append("EXPECTED_BASE_MISMATCH")
    if not (_sha(head) and _sha(base) and _checks_ok(s.get("required_checks"), head, base, s.get("required_check_sources"))): fail.append("REQUIRED_CHECKS_INVALID")
    if not (_sha(head) and _sha(base) and _checks_ok(s.get("security_checks"), head, base, s.get("security_check_sources"))): fail.append("SECURITY_CHECKS_INVALID")
    if not (_sha(head) and _sha(base) and _review_ok(s.get("review"), head, base)): fail.append("REVIEW_INVALID")
    return not fail, tuple(fail)

def classify_item(s: Mapping[str, Any], budget: Budget):
    if budget.exhausted(): return ItemState.PARKED
    if s.get("no_actionable_work") is True: return ItemState.IDLE
    if s.get("governed_path_touched") is True or s.get("test_weakening") is True: return ItemState.GOVERNANCE_CHANGE
    if s.get("needs_human") is True: return ItemState.BLOCK_HUMAN
    if s.get("dependency_wait") is True: return ItemState.WAIT_DEPENDENCY
    if s.get("merged") is True:
        if s.get("post_merge_verified") is True: return ItemState.MERGED_VERIFIED
        if s.get("main_broken") is True: return ItemState.MAIN_BROKEN
        return ItemState.MERGED_UNVERIFIED
    if s.get("merge_outcome_unknown") is True: return ItemState.MERGE_OUTCOME_UNKNOWN
    if s.get("merge_queued") is True: return ItemState.MERGE_QUEUED
    if s.get("superseded") is True: return ItemState.SUPERSEDED
    if s.get("disputed_finding") is True: return ItemState.DISPUTED_FINDING
    if s.get("findings_open") is True: return ItemState.FINDINGS_OPEN
    if s.get("behind_base") is True: return ItemState.BEHIND_BASE
    ci = s.get("ci")
    if ci in (None, "PENDING"): return ItemState.WAIT_CI
    if ci == "MISSING": return ItemState.CI_MISSING
    if ci == "INFRA_FAILED": return ItemState.CI_RED_INFRA
    if ci == "DETERMINISTIC_FAILED": return ItemState.CI_RED_DETERMINISTIC
    if ci != "GREEN": return ItemState.WAIT_CI
    if s.get("provider_unavailable") is True: return ItemState.WAIT_PROVIDER
    if s.get("independent_review_pass") is not True: return ItemState.CI_GREEN_UNREVIEWED
    return ItemState.MERGE_ELIGIBLE if merge_ok(s)[0] else ItemState.FINDINGS_OPEN

def selftest():
    st = MemoryCASStore(); obs = Observation("a"*40, "b"*40, "wu", "t"); key = lease_key("repo", "pr", "1", "MERGE")
    lease = acquire(st, key, new_run_id(), obs, now_srv=1000); assert lease is not None
    assert acquire(st, key, new_run_id(), obs, now_srv=1001) is None
    li = attach_intent(st, lease, "repo", "pr:1", "merge"); assert li is not None
    assert fence_ok(st, "repo", li, obs, now_srv=1010) == (True, "OK")
    assert intent_recovery(li, "UNKNOWN") == "READBACK_REQUIRED"
    print("l5_kernel selftest PASS")
if __name__ == "__main__": selftest()
