"""API-level hostile scheduler for L5 post-Claude certification.

This module intentionally models only the concurrency/fault boundary needed by
A1-A12. It is deterministic for a seed, but each trace varies object values,
actor order and selected fault placement. Safety is asserted after every
trace; no GitHub or network writes occur here.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SimState:
    head: str
    base: str
    epoch: int = 1
    hold: bool = False
    review_ok: bool = True
    checks_ok: bool = True
    rules_ok: bool = True
    merged: bool = False
    mutation_count: int = 0
    merge_calls: int = 0
    external_marker: float = 0.0


@dataclass(frozen=True)
class FaultPlan:
    stale_reads: frozenset[int] = frozenset()
    partial_reads: frozenset[int] = frozenset()
    drop_after_apply: frozenset[str] = frozenset()


@dataclass
class SimAPI:
    state: SimState
    faults: FaultPlan
    calls: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def read(self) -> dict[str, Any]:
        self.calls += 1
        live = copy.deepcopy(self.state.__dict__)
        self.history.append(live)
        if self.calls in self.faults.stale_reads and len(self.history) > 1:
            return copy.deepcopy(self.history[-2])
        if self.calls in self.faults.partial_reads:
            live.pop("review_ok", None)
            live.pop("checks_ok", None)
            if self.calls == 1:
                live.pop("head", None)
            return live
        return live

    def external_change(self, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(self.state, key, value)

    def push(self, expected_head: str, new_head: str, expected_epoch: int) -> dict[str, Any]:
        self.calls += 1
        if self.state.head != expected_head or self.state.epoch != expected_epoch:
            return {"status": "BLOCKED", "reason": "CAS_MISMATCH"}
        self.state.head = new_head
        self.state.mutation_count += 1
        if "push" in self.faults.drop_after_apply:
            return {"status": "UNKNOWN", "reason": "RESPONSE_DROPPED"}
        return {"status": "COMPLETE"}

    def merge(self, expected_head: str, expected_base: str, expected_epoch: int) -> dict[str, Any]:
        self.calls += 1
        self.state.merge_calls += 1
        if self.state.merged:
            return {"status": "BLOCKED", "reason": "ALREADY_MERGED"}
        if self.state.head != expected_head or self.state.base != expected_base or self.state.epoch != expected_epoch:
            return {"status": "BLOCKED", "reason": "CAS_MISMATCH"}
        if self.state.hold or not self.state.review_ok or not self.state.checks_ok or not self.state.rules_ok:
            return {"status": "BLOCKED", "reason": "LIVE_GATE_FALSE"}
        self.state.merged = True
        self.state.mutation_count += 1
        if "merge" in self.faults.drop_after_apply:
            return {"status": "UNKNOWN", "reason": "RESPONSE_DROPPED"}
        return {"status": "COMPLETE"}


def _sha(rng: random.Random, prefix: str) -> str:
    alphabet = "0123456789abcdef"
    return prefix + "".join(rng.choice(alphabet) for _ in range(39))


def final_merge(api: SimAPI, observed: dict[str, Any], epoch: int) -> dict[str, Any]:
    """Final exact-state reconcile before the simulated irreversible write."""
    if not isinstance(observed.get("head"), str) or not isinstance(observed.get("base"), str):
        return {"status": "BLOCKED", "reason": "EVIDENCE_INCOMPLETE"}
    final = api.read()
    required = ("head", "base", "hold", "review_ok", "checks_ok", "rules_ok", "merged")
    if any(key not in final for key in required):
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
    stale_slot = rng.choice([2, 2, 3])
    partial_slot = rng.choice([1, 2])
    actor_order = ["A", "B"]
    rng.shuffle(actor_order)

    if sid == 1:
        api = SimAPI(state, FaultPlan(stale_reads=frozenset({stale_slot})))
        observed = api.read()
        api.external_change(hold=True, epoch=state.epoch + rng.randint(1, 3))
        result = final_merge(api, observed, int(observed.get("epoch", 1)))
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 2:
        api = SimAPI(state, FaultPlan(drop_after_apply=frozenset({"merge"})))
        observed = api.read()
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "UNKNOWN" and state.merged
        readback = api.read()
        assert readback.get("merged") is True and state.merge_calls == 1
    elif sid == 3:
        api = SimAPI(state, FaultPlan(drop_after_apply=frozenset({"push"})))
        observed = api.read()
        new_head = _sha(rng, "c")
        result = api.push(str(observed["head"]), new_head, state.epoch)
        assert result["status"] == "UNKNOWN"
        assert api.read().get("head") == new_head and state.mutation_count == 1
    elif sid == 4:
        api = SimAPI(state, FaultPlan(stale_reads=frozenset({2})))
        observed = api.read()
        state.external_marker = rng.random()
        api.external_change(base=_sha(rng, "d"))
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 5:
        api = SimAPI(state, FaultPlan(stale_reads=frozenset({stale_slot})))
        observed = api.read()
        api.external_change(review_ok=False)
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 6:
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        api.external_change(rules_ok=False)
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 7:
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        results = []
        for actor in actor_order:
            results.append(api.push(str(observed["head"]), _sha(rng, actor.lower()), state.epoch))
        assert sum(result["status"] == "COMPLETE" for result in results) == 1
    elif sid == 8:
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        final_observations = [api.read() for _actor in actor_order]
        required = ("head", "base", "hold", "review_ok", "checks_ok", "rules_ok", "merged")
        assert all(all(key in final for key in required) for final in final_observations)
        assert all(final["head"] == observed["head"] and final["base"] == observed["base"] for final in final_observations)
        results = [api.merge(str(final["head"]), str(final["base"]), state.epoch) for final in final_observations]
        assert state.merge_calls == 2
        assert sum(result["status"] == "COMPLETE" for result in results) == 1
        assert state.mutation_count == 1
    elif sid == 9:
        api = SimAPI(state, FaultPlan(partial_reads=frozenset({partial_slot})))
        observed = api.read()
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 10:
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        old_epoch = state.epoch
        api.external_change(epoch=old_epoch + rng.randint(1, 4))
        result = api.push(str(observed["head"]), _sha(rng, "e"), old_epoch)
        assert result["status"] == "BLOCKED" and state.mutation_count == 0
    elif sid == 11:
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        api.external_change(head=_sha(rng, "f"), review_ok=False)
        api.external_change(head=head)
        result = final_merge(api, observed, state.epoch)
        assert result["status"] == "BLOCKED" and not state.merged
    elif sid == 12:
        api = SimAPI(state, FaultPlan())
        observed = api.read()
        api.external_change(base=_sha(rng, "9"), epoch=state.epoch + 1)
        result = final_merge(api, observed, int(observed.get("epoch", 1)))
        assert result["status"] == "BLOCKED" and not state.merged
    else:
        raise AssertionError(f"unknown scenario {sid}")


def run(*, rounds: int = 1000, seed: int = 20261001) -> dict[str, int]:
    if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
        raise ValueError("rounds must be >= 1")
    rng = random.Random(seed)
    traces = 0
    for _ in range(rounds):
        order = list(range(1, 13))
        rng.shuffle(order)
        for sid in order:
            scenario(sid, rng)
            traces += 1
    return {"rounds": rounds, "scenarios": 12, "traces": traces, "seed": seed}


run_simulation = run


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be >= 1")
    print(run(rounds=args.rounds, seed=args.seed))
