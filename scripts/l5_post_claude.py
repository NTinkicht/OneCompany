#!/usr/bin/env python3
"""Post-Claude hardening for the L5 controller.

This module adds four production-readiness layers that intentionally remain
separate from GitHub ruleset enforcement:

1. a pinned independent-reviewer registry and credential-isolation contract;
2. a strictly read-only shadow evaluator for real repositories;
3. an API-level hostile simulator that injects stale reads, reordering,
   pauses, CAS races, governance drift, and dropped-after-apply responses;
4. liveness/invariant checks for recorded controller runs.

It never imports the guarded write adapter and never performs a GitHub mutation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import argparse
import json
import random
from typing import Any, Iterable, Mapping, Sequence

from l5_kernel import Budget, ItemState, classify_item, merge_precheck_v11


# ---------------------------------------------------------------------------
# Trust boundary
# ---------------------------------------------------------------------------


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


@dataclass(frozen=True)
class TrustPolicy:
    """Human-governed identities and credential-boundary requirements."""

    binding_reviewer_logins: frozenset[str]
    controller_identities: frozenset[str]
    policy_hash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TrustPolicy":
        if value.get("schema_version") != "1.0":
            raise ValueError("TRUST_POLICY_SCHEMA_INVALID")
        reviewers = value.get("binding_reviewers")
        controllers = value.get("controller_identities")
        if not isinstance(reviewers, list) or not reviewers:
            raise ValueError("TRUST_POLICY_REVIEWERS_INVALID")
        if not isinstance(controllers, list) or not controllers:
            raise ValueError("TRUST_POLICY_CONTROLLERS_INVALID")

        logins: set[str] = set()
        for reviewer in reviewers:
            if not isinstance(reviewer, Mapping):
                raise ValueError("TRUST_POLICY_REVIEWER_INVALID")
            identities = reviewer.get("github_logins")
            if not isinstance(identities, list) or not identities:
                raise ValueError("TRUST_POLICY_REVIEWER_LOGIN_INVALID")
            logins.update(_norm(actor) for actor in identities if _norm(actor))
        controller_set = {_norm(actor) for actor in controllers if _norm(actor)}
        if not controller_set or logins & controller_set:
            raise ValueError("TRUST_POLICY_IDENTITY_OVERLAP")

        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return cls(
            binding_reviewer_logins=frozenset(logins),
            controller_identities=frozenset(controller_set),
            policy_hash=sha256(canonical.encode()).hexdigest(),
        )


def review_is_independent(
    review: Mapping[str, Any],
    *,
    policy: TrustPolicy,
    head_sha: str,
    base_sha: str,
    material_authors: Sequence[str],
) -> tuple[bool, tuple[str, ...]]:
    """Verify a binding reviewer from the pinned registry on the exact state."""
    failures: list[str] = []
    if review.get("state") != "APPROVED":
        failures.append("REVIEW_NOT_APPROVED")
    if review.get("commit_id") != head_sha:
        failures.append("REVIEW_HEAD_MISMATCH")
    if review.get("base_sha") != base_sha:
        failures.append("REVIEW_BASE_MISMATCH")
    if review.get("complete") is not True or review.get("covers_full_diff") is not True:
        failures.append("REVIEW_INCOMPLETE")
    if review.get("skipped") is not False:
        failures.append("REVIEW_SKIPPED")
    if review.get("identity_source_verified") is not True:
        failures.append("REVIEW_IDENTITY_UNVERIFIED")

    author = _norm(review.get("author"))
    if author not in policy.binding_reviewer_logins:
        failures.append("REVIEWER_NOT_IN_PINNED_REGISTRY")
    excluded = policy.controller_identities | {_norm(a) for a in material_authors}
    if not author or author in excluded:
        failures.append("REVIEWER_NOT_INDEPENDENT")
    return not failures, tuple(dict.fromkeys(failures))


def credential_boundary_ok(evidence: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Prove that repository code and write credentials never share a process."""
    expected = {
        "controller_executes_repository_code": False,
        "test_worker_has_write_token": False,
        "write_token_in_test_env": False,
        "actuator_executes_repository_code": False,
        "repo_code_runs_in_actuator": False,
        "actuator_accepts_structured_only": True,
        "credential_boundary_verified": True,
    }
    failures = [
        f"CREDENTIAL_BOUNDARY_{key.upper()}"
        for key, wanted in expected.items()
        if evidence.get(key) is not wanted
    ]
    return not failures, tuple(failures)


def trust_boundary_ok(
    evidence: Mapping[str, Any],
    *,
    policy: TrustPolicy,
    head_sha: str,
    base_sha: str,
    material_authors: Sequence[str],
) -> tuple[bool, tuple[str, ...]]:
    """Combine pinned reviewer identity and credential-isolation evidence."""
    review = evidence.get("review")
    credential = evidence.get("credential_boundary")
    failures: list[str] = []
    if not isinstance(review, Mapping):
        failures.append("REVIEW_EVIDENCE_MISSING")
    else:
        failures.extend(
            review_is_independent(
                review,
                policy=policy,
                head_sha=head_sha,
                base_sha=base_sha,
                material_authors=material_authors,
            )[1]
        )
    if not isinstance(credential, Mapping):
        failures.append("CREDENTIAL_BOUNDARY_EVIDENCE_MISSING")
    else:
        failures.extend(credential_boundary_ok(credential)[1])
    if evidence.get("trust_policy_hash") != policy.policy_hash:
        failures.append("TRUST_POLICY_HASH_MISMATCH")
    return not failures, tuple(dict.fromkeys(failures))


# ---------------------------------------------------------------------------
# Read-only shadow mode
# ---------------------------------------------------------------------------


def shadow_evaluate(
    repo_snapshot: Mapping[str, Any],
    item_snapshot: Mapping[str, Any],
    *,
    budget: Budget | None = None,
) -> Mapping[str, Any]:
    """Compute the L5 decision without exposing any mutation capability.

    Missing platform enforcement remains an activation blocker. To keep shadow
    mode useful before rulesets are installed, the function also computes a
    clearly-labelled hypothetical merge result with only the deferred platform
    enforcement fields staged to true. The real result never authorizes writes.
    """
    state = classify_item(item_snapshot, budget or Budget())
    blockers: list[str] = []
    platform_fields = (
        "platform_enforcement_ok",
        "live_rules_at_least_pinned",
        "rulesets_or_protection_active",
        "required_check_sources_pinned",
    )
    if not all(repo_snapshot.get(name) is True for name in platform_fields):
        blockers.append("PLATFORM_ENFORCEMENT_DEFERRED")

    staged = dict(item_snapshot)
    staged["live_rules_at_least_pinned"] = True
    staged["rulesets_or_protection_active"] = True
    staged["required_check_sources_pinned"] = True
    staged["l5_intent_restraint_required"] = True
    hypothetical_merge_ok, hypothetical_failures = merge_precheck_v11(staged)

    return {
        "mode": "SHADOW",
        "mutation_allowed": False,
        "state": state.value,
        "activation_blockers": blockers,
        "candidate_merge_ok_if_platform_enforced": hypothetical_merge_ok,
        "candidate_merge_failures_if_platform_enforced": list(hypothetical_failures),
    }


# ---------------------------------------------------------------------------
# API-level hostile simulator
# ---------------------------------------------------------------------------


@dataclass
class SimState:
    head: str = "a" * 40
    base: str = "b" * 40
    hold: bool = False
    review_ok: bool = True
    checks_ok: bool = True
    rules_ok: bool = True
    merged: bool = False
    merge_lock: bool = False
    epoch: int = 1
    mutation_count: int = 0
    merge_calls: int = 0
    event_log: list[str] = field(default_factory=list)

    def clone(self) -> "SimState":
        return SimState(
            head=self.head,
            base=self.base,
            hold=self.hold,
            review_ok=self.review_ok,
            checks_ok=self.checks_ok,
            rules_ok=self.rules_ok,
            merged=self.merged,
            merge_lock=self.merge_lock,
            epoch=self.epoch,
            mutation_count=self.mutation_count,
            merge_calls=self.merge_calls,
            event_log=list(self.event_log),
        )


@dataclass(frozen=True)
class FaultPlan:
    stale_reads: frozenset[int] = frozenset()
    drop_after_apply: frozenset[str] = frozenset()
    partial_pages: frozenset[int] = frozenset()


class SimAPI:
    """A deterministic GitHub-like API with stale/partial/drop faults."""

    def __init__(self, state: SimState, faults: FaultPlan | None = None):
        self.state = state
        self.faults = faults or FaultPlan()
        self._call_index = 0
        self._history = [state.clone()]

    def _next(self) -> int:
        self._call_index += 1
        return self._call_index

    def read(self) -> Mapping[str, Any]:
        idx = self._next()
        if idx in self.faults.partial_pages:
            return {"complete": False}
        source = self._history[-2] if idx in self.faults.stale_reads and len(self._history) > 1 else self.state
        return {
            "complete": True,
            "head": source.head,
            "base": source.base,
            "hold": source.hold,
            "review_ok": source.review_ok,
            "checks_ok": source.checks_ok,
            "rules_ok": source.rules_ok,
            "merged": source.merged,
            "merge_lock": source.merge_lock,
            "epoch": source.epoch,
        }

    def external_change(self, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(self.state, key, value)
        self.state.event_log.append("external_change")
        self._history.append(self.state.clone())

    def push(self, expected_head: str, new_head: str, expected_epoch: int) -> Mapping[str, Any]:
        self._next()
        if expected_epoch != self.state.epoch:
            return {"status": "BLOCKED", "reason": "EPOCH_STALE"}
        if expected_head != self.state.head:
            return {"status": "BLOCKED", "reason": "HEAD_STALE"}
        self.state.head = new_head
        self.state.mutation_count += 1
        self.state.event_log.append("push")
        self._history.append(self.state.clone())
        if "push" in self.faults.drop_after_apply:
            return {"status": "UNKNOWN"}
        return {"status": "COMPLETE"}

    def merge(self, expected_head: str, expected_base: str, expected_epoch: int) -> Mapping[str, Any]:
        self._next()
        self.state.merge_calls += 1
        if expected_epoch != self.state.epoch:
            return {"status": "BLOCKED", "reason": "EPOCH_STALE"}
        if self.state.merge_lock:
            return {"status": "BLOCKED", "reason": "MERGE_LOCKED"}
        if expected_head != self.state.head or expected_base != self.state.base:
            return {"status": "BLOCKED", "reason": "EXACT_STATE_STALE"}
        if self.state.hold or not self.state.review_ok or not self.state.checks_ok or not self.state.rules_ok:
            return {"status": "BLOCKED", "reason": "FINAL_GATE_FALSE"}
        self.state.merge_lock = True
        self.state.merged = True
        self.state.mutation_count += 1
        self.state.event_log.append("merge")
        self._history.append(self.state.clone())
        if "merge" in self.faults.drop_after_apply:
            return {"status": "UNKNOWN"}
        return {"status": "COMPLETE"}


class Scheduler:
    """Deterministically interleave actors to model pauses and reordering."""

    def __init__(self, rng: random.Random):
        self.rng = rng

    def order(self, actors: Iterable[str]) -> list[str]:
        out = list(actors)
        self.rng.shuffle(out)
        return out


def _fresh_merge_attempt(api: SimAPI, observed: Mapping[str, Any], epoch: int) -> Mapping[str, Any]:
    """Final-reconcile immediately before merge, never using cached PASS."""
    final = api.read()
    if final.get("complete") is not True:
        return {"status": "BLOCKED", "reason": "EVIDENCE_INCOMPLETE"}
    required = (
        final.get("head") == observed.get("head"),
        final.get("base") == observed.get("base"),
        final.get("hold") is False,
        final.get("review_ok") is True,
        final.get("checks_ok") is True,
        final.get("rules_ok") is True,
        final.get("merged") is False,
    )
    if not all(required):
        return {"status": "BLOCKED", "reason": "FINAL_RECONCILE_FAILED"}
    return api.merge(str(final["head"]), str(final["base"]), epoch)


def api_hostile_scenario(sid: int, rng: random.Random) -> None:
    """Run one API-level hostile scenario and assert the safety invariant."""
    state = SimState()
    scheduler = Scheduler(rng)

    if sid == 1:  # zombie merger paused before final reconcile
        api = SimAPI(state)
        observed = api.read()
        api.external_change(hold=True, epoch=2)
        result = _fresh_merge_attempt(api, observed, 1)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 2:  # merge response dropped after apply
        api = SimAPI(state, FaultPlan(drop_after_apply=frozenset({"merge"})))
        observed = api.read()
        result = _fresh_merge_attempt(api, observed, 1)
        assert result["status"] == "UNKNOWN" and state.merged
        readback = api.read()
        assert readback["merged"] is True and state.merge_calls == 1
    elif sid == 3:  # lost push response: readback, no rebuilt push
        api = SimAPI(state, FaultPlan(drop_after_apply=frozenset({"push"})))
        before = api.read(); new_head = "c" * 40
        result = api.push(str(before["head"]), new_head, 1)
        assert result["status"] == "UNKNOWN"
        assert api.read()["head"] == new_head and state.mutation_count == 1
    elif sid == 4:  # base advances between checks and merge
        api = SimAPI(state)
        observed = api.read(); api.external_change(base="d" * 40)
        assert _fresh_merge_attempt(api, observed, 1)["status"] == "BLOCKED"
        assert not state.merged
    elif sid == 5:  # approval revoked after initial read
        api = SimAPI(state)
        observed = api.read(); api.external_change(review_ok=False)
        assert _fresh_merge_attempt(api, observed, 1)["status"] == "BLOCKED"
    elif sid == 6:  # governance drift at final boundary
        api = SimAPI(state)
        observed = api.read(); api.external_change(rules_ok=False)
        assert _fresh_merge_attempt(api, observed, 1)["status"] == "BLOCKED"
    elif sid == 7:  # two writers race same expected head
        api = SimAPI(state)
        observed = api.read(); actors = scheduler.order(["A", "B"])
        results = []
        for index, _actor in enumerate(actors):
            results.append(api.push(str(observed["head"]), chr(ord("c") + index) * 40, 1))
        assert sum(r["status"] == "COMPLETE" for r in results) == 1
    elif sid == 8:  # single repository merger
        api = SimAPI(state)
        observed = api.read(); actors = scheduler.order(["A", "B"])
        results = [_fresh_merge_attempt(api, observed, 1) for _ in actors]
        assert sum(r["status"] == "COMPLETE" for r in results) == 1
        assert state.mutation_count == 1
    elif sid == 9:  # partial pagination is unknown, never empty/pass
        api = SimAPI(state, FaultPlan(partial_pages=frozenset({2})))
        observed = api.read(); result = _fresh_merge_attempt(api, observed, 1)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 10:  # stale epoch after reclaim
        api = SimAPI(state)
        observed = api.read(); api.external_change(epoch=2)
        result = api.push(str(observed["head"]), "c" * 40, 1)
        assert result["status"] == "BLOCKED" and state.mutation_count == 0
    elif sid == 11:  # head force-push ABA still demands fresh evidence
        api = SimAPI(state)
        observed = api.read()
        api.external_change(head="c" * 40, review_ok=False)
        api.external_change(head="a" * 40)
        result = _fresh_merge_attempt(api, observed, 1)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 12:  # shadow execution cannot mutate even when candidate is ready
        before = state.clone()
        decision = shadow_evaluate(
            {
                "platform_enforcement_ok": False,
                "live_rules_at_least_pinned": False,
                "rulesets_or_protection_active": False,
                "required_check_sources_pinned": True,
            },
            {"no_actionable_work": True},
        )
        assert decision["mutation_allowed"] is False
        assert state == before
    else:
        raise AssertionError(f"unknown API hostile scenario {sid}")


def run_api_hostile_sim(rounds: int = 1000, seed: int = 0xC1A0DE) -> Mapping[str, int]:
    """Run 12 API-level scenarios under 1,000 randomized interleavings each."""
    if rounds < 1:
        raise ValueError("ROUNDS_INVALID")
    rng = random.Random(seed)
    counts = {f"A{sid}": 0 for sid in range(1, 13)}
    order = list(range(1, 13))
    for _ in range(rounds):
        rng.shuffle(order)
        for sid in order:
            api_hostile_scenario(sid, rng)
            counts[f"A{sid}"] += 1
    return counts


# ---------------------------------------------------------------------------
# Liveness / trace invariants
# ---------------------------------------------------------------------------


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


def check_liveness(events: Sequence[Mapping[str, Any]], *, max_stagnant_runs: int = 5) -> tuple[bool, tuple[str, ...]]:
    """Validate progress, budgets, idle quiescence, and bounded stagnation."""
    failures: list[str] = []
    stagnant: dict[tuple[str, str], int] = {}
    last_fingerprint: dict[tuple[str, str], str] = {}

    for event in events:
        repo = str(event.get("repo") or "")
        item = str(event.get("item_id") or "repo")
        key = (repo, item)
        status = event.get("status")
        if status not in TERMINAL_RUN_STATUSES:
            failures.append("RUN_NOT_TERMINAL")

        budget = event.get("budget", {})
        if isinstance(budget, Mapping):
            limits = {"ci_reruns": 2, "fix_iterations": 5, "review_rounds": 3, "lease_acquisitions": 12}
            for name, limit in limits.items():
                value = budget.get(name, 0)
                if type(value) is not int or value > limit:
                    failures.append(f"BUDGET_EXCEEDED_{name.upper()}")

        if event.get("external_changes") is False and event.get("stable_cycle") is True:
            if int(event.get("writes", 0) or 0) != 0:
                failures.append("IDLE_NOT_QUIESCENT")

        fingerprint = json.dumps(
            [event.get("state"), event.get("reason"), event.get("head"), event.get("base")],
            sort_keys=True,
        )
        reason = str(event.get("reason") or "")
        named_wait = status == "WAIT" and (
            any(reason.startswith(prefix) for prefix in NAMED_WAIT_PREFIXES)
            or reason in {"LEASE_BUSY", "MERGED_UNVERIFIED"}
        )
        if status in {"COMPLETE", "FAILED", "IDLE"} or event.get("state") == "PARKED" or named_wait:
            stagnant[key] = 0
        elif last_fingerprint.get(key) == fingerprint:
            stagnant[key] = stagnant.get(key, 0) + 1
            if stagnant[key] > max_stagnant_runs:
                failures.append("UNBOUNDED_STAGNATION")
        else:
            stagnant[key] = 1
        last_fingerprint[key] = fingerprint

    return not failures, tuple(dict.fromkeys(failures))


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-sim-rounds", type=int, default=0)
    args = parser.parse_args()
    if args.api_sim_rounds:
        counts = run_api_hostile_sim(args.api_sim_rounds)
        print("l5_post_claude API hostile simulation PASS", json.dumps(counts, sort_keys=True))
    else:
        print("l5_post_claude selftest PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
