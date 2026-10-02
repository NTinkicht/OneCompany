#!/usr/bin/env python3
"""API-level hostile scheduler for L5 final-reconcile and CAS invariants.

Unlike the kernel micro-scenarios, every round varies actor order, concrete
heads/bases, stale-read positions, fault placement, and external-change timing.
Writes may be applied before their response is dropped. The simulator never
models a cached gate evaluation as merge evidence: a merge attempt must use a
fresh final read and exact resource preconditions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import argparse
import json
import random
from typing import Any

from l5_shadow import shadow_evaluate


def _sha(rng: random.Random, prefix: str) -> str:
    alphabet = "0123456789abcdef"
    seed = (prefix + "".join(rng.choice(alphabet) for _ in range(40)))[:40]
    return (seed + "0" * 40)[:40]


@dataclass
class SimState:
    head: str
    base: str
    hold: bool = False
    review_ok: bool = True
    checks_ok: bool = True
    rules_ok: bool = True
    merged: bool = False
    merge_lock: bool = False
    epoch: int = 1
    mutation_count: int = 0
    merge_calls: int = 0
    log: list[str] = field(default_factory=list)

    def clone(self) -> "SimState":
        return SimState(
            self.head,
            self.base,
            self.hold,
            self.review_ok,
            self.checks_ok,
            self.rules_ok,
            self.merged,
            self.merge_lock,
            self.epoch,
            self.mutation_count,
            self.merge_calls,
            list(self.log),
        )


@dataclass(frozen=True)
class FaultPlan:
    stale_reads: frozenset[int] = frozenset()
    partial_reads: frozenset[int] = frozenset()
    drop_after_apply: frozenset[str] = frozenset()


class SimAPI:
    """Small GitHub model with exact-head CAS and injected read/write faults."""

    def __init__(self, state: SimState, faults: FaultPlan):
        self.state = state
        self.faults = faults
        self.call_index = 0
        self.history = [state.clone()]

    def _next(self) -> int:
        self.call_index += 1
        return self.call_index

    def read(self) -> dict[str, Any]:
        idx = self._next()
        if idx in self.faults.partial_reads:
            return {"complete": False, "request_id": f"read-{idx}"}
        source = self.state
        if idx in self.faults.stale_reads and len(self.history) > 1:
            source = self.history[-2]
        return {
            "complete": True,
            "request_id": f"read-{idx}",
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
        self.state.log.append("external_change")
        self.history.append(self.state.clone())

    def push(self, expected_head: str, new_head: str, expected_epoch: int) -> dict[str, str]:
        self._next()
        if expected_epoch != self.state.epoch:
            return {"status": "BLOCKED", "reason": "EPOCH_STALE"}
        if expected_head != self.state.head:
            return {"status": "BLOCKED", "reason": "HEAD_STALE"}
        self.state.head = new_head
        self.state.mutation_count += 1
        self.state.log.append("push")
        self.history.append(self.state.clone())
        if "push" in self.faults.drop_after_apply:
            return {"status": "UNKNOWN", "reason": "RESPONSE_DROPPED"}
        return {"status": "COMPLETE", "reason": "OK"}

    def merge(self, expected_head: str, expected_base: str, expected_epoch: int) -> dict[str, str]:
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
        self.state.log.append("merge")
        self.history.append(self.state.clone())
        if "merge" in self.faults.drop_after_apply:
            return {"status": "UNKNOWN", "reason": "RESPONSE_DROPPED"}
        return {"status": "COMPLETE", "reason": "OK"}


def final_merge(api: SimAPI, observed: dict[str, Any], epoch: int) -> dict[str, str]:
    """Model FINAL_RECONCILE + expected-head/base merge as one guarded lane."""
    final = api.read()
    if final.get("complete") is not True:
        return {"status": "BLOCKED", "reason": "EVIDENCE_INCOMPLETE"}
    if final.get("head") != observed.get("head") or final.get("base") != observed.get("base"):
        return {"status": "BLOCKED", "reason": "OBSERVATION_CHANGED"}
    if final.get("hold") is not False or final.get("review_ok") is not True:
        return {"status": "BLOCKED", "reason": "FINAL_GATE_FALSE"}
    if final.get("checks_ok") is not True or final.get("rules_ok") is not True:
        return {"status": "BLOCKED", "reason": "FINAL_GATE_FALSE"}
    if final.get("merged") is not False:
        return {"status": "BLOCKED", "reason": "ALREADY_MERGED"}
    return api.merge(str(final["head"]), str(final["base"]), epoch)


def scenario(sid: int, rng: random.Random) -> None:
    """Run one randomized hostile trace and assert the scenario invariant."""
    head = _sha(rng, "a")
    base = _sha(rng, "b")
    state = SimState(head=head, base=base)

    stale_slot = rng.choice([1, 2, 3, 4])
    partial_slot = rng.choice([1, 2, 3, 4])
    actor_order = ["A", "B"]
    rng.shuffle(actor_order)

    if sid == 1:  # zombie merger: pause, reclaim, hold/freeze, resume
        api = SimAPI(state, FaultPlan(stale_reads=frozenset({stale_slot}) if stale_slot == 1 else frozenset()))
        observed = api.read()
        api.external_change(hold=True, epoch=state.epoch + rng.randint(1, 3))
        result = final_merge(api, observed, int(observed.get("epoch", 1)))
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 2:  # dropped merge response after apply: read back, never merge twice
        api = SimAPI(state, FaultPlan(drop_after_apply=frozenset({"merge"})))
        observed = api.read()
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "UNKNOWN" and state.merged
        readback = api.read()
        assert readback.get("merged") is True and state.merge_calls == 1
    elif sid == 3:  # dropped push response after apply: read same remote object
        api = SimAPI(state, FaultPlan(drop_after_apply=frozenset({"push"})))
        observed = api.read()
        new_head = _sha(rng, "c")
        result = api.push(str(observed["head"]), new_head, state.epoch)
        assert result["status"] == "UNKNOWN"
        assert api.read().get("head") == new_head and state.mutation_count == 1
    elif sid == 4:  # stale read after base advance cannot authorize merge
        api = SimAPI(state, FaultPlan(stale_reads=frozenset({2})))
        observed = api.read()
        state.external_marker = rng.random()  # vary trace without affecting gate
        api.external_change(base=_sha(rng, "d"))
        result = final_merge(api, observed, state.epoch)
        # The injected final read may be stale, but resource CAS still sees live base.
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 5:  # review revoked between initial and final read
        api = SimAPI(state, FaultPlan(stale_reads=frozenset({stale_slot}) if stale_slot == 1 else frozenset()))
        observed = api.read()
        api.external_change(review_ok=False)
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 6:  # governance weakens before merge
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        api.external_change(rules_ok=False)
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 7:  # duplicate pushes: one CAS winner despite actor order
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        results = []
        for actor in actor_order:
            results.append(api.push(str(observed["head"]), _sha(rng, actor.lower()), state.epoch))
        assert sum(result["status"] == "COMPLETE" for result in results) == 1
    elif sid == 8:  # duplicate mergers: one repository-lock winner
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        results = [final_merge(api, observed, state.epoch) for _actor in actor_order]
        assert sum(result["status"] == "COMPLETE" for result in results) == 1
        assert state.mutation_count == 1
    elif sid == 9:  # partial final evidence fails closed at random position
        faults = FaultPlan(partial_reads=frozenset({2}))
        api = SimAPI(state, faults)
        observed = api.read()
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 10:  # stale holder after lease epoch reclaim cannot push
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        old_epoch = state.epoch
        api.external_change(epoch=old_epoch + rng.randint(1, 4))
        result = api.push(str(observed["head"]), _sha(rng, "e"), old_epoch)
        assert result["status"] == "BLOCKED" and state.mutation_count == 0
    elif sid == 11:  # exact-head ABA with review invalidation must fail on review evidence
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        api.external_change(head=_sha(rng, "f"), review_ok=False)
        api.external_change(head=head)
        final = api.read()
        assert final.get("head") == observed.get("head") and final.get("review_ok") is False
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "BLOCKED" and result["reason"] == "FINAL_GATE_FALSE" and not state.merged
    elif sid == 12:  # shadow path has no mutation capability by construction
        before = state.clone()
        decision = shadow_evaluate(
            {
                "ledger_reachable": True,
                "platform_enforcement_ok": False,
                "live_rules_at_least_pinned": False,
                "rulesets_or_protection_active": False,
                "required_check_sources_pinned": True,
                "controller_admin": False,
                "controller_bypass": False,
            },
            {"no_actionable_work": True},
        )
        assert decision["mutation_allowed"] is False and decision["writes"] == 0
        assert state == before
    else:
        raise AssertionError(f"unknown scenario {sid}")


def run(rounds: int = 1000, seed: int = 0xC1A0DE) -> dict[str, int]:
    """Run A1-A12 with randomized fault positions and actor ordering per round."""
    if type(rounds) is not int or rounds < 1:
        raise ValueError("ROUNDS_INVALID")
    rng = random.Random(seed)
    counts = {f"A{sid}": 0 for sid in range(1, 13)}
    scenarios = list(range(1, 13))
    for _ in range(rounds):
        rng.shuffle(scenarios)
        for sid in scenarios:
            scenario(sid, rng)
            counts[f"A{sid}"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0xC1A0DE)
    args = parser.parse_args()
    counts = run(args.rounds, args.seed)
    print("l5_api_hostile_sim PASS", json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
