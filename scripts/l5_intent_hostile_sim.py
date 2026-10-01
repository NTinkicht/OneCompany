#!/usr/bin/env python3
"""L5.1 hostile certification scenarios S31-S40 (10,000 traces)."""
from __future__ import annotations

import random
from l5_kernel import intent_restraint_status

HEX = "0123456789abcdef"


def valid(rng: random.Random):
    h = rng.choice(HEX) * 40
    b = rng.choice(HEX) * 40
    if b == h: b = ("f" if h[0] != "f" else "e") * 40
    wu = f"wu-{rng.randrange(1_000_000_000)}"
    evidence = {
        "state": "PASS", "head_sha": h, "base_sha": b, "wu_body_hash": wu,
        "complete": True, "designated_independent": True, "reviewer_eligible": True,
        "identity_source_verified": True, "wu_contract_frozen": True,
        "intent_preserved": True, "scope_discipline_verified": True,
        "minimal_change_verified": True, "no_overengineering": True,
        "existing_mechanism_reused_or_justified": True, "conventions_preserved": True,
        "architecture_consistent": True, "performance_preserved": True,
        "api_semantics_preserved": True, "diff_proportionate": True,
        "adversarial_deletion_review_complete": True, "deletion_candidates_resolved": True,
        "failure_reasons": [], "author": "external-reviewer",
        "material_authors": ["chatgpt"], "controller_identities": ["controller"],
        "material_authors_head_sha": h,
    }
    return {"head_sha": h, "base_sha": b, "wu_body_hash": wu, "intent_restraint": evidence}


def scenario(sid: int, rng: random.Random):
    snap = valid(rng); ev = dict(snap["intent_restraint"]); snap["intent_restraint"] = ev
    if sid == 31: ev["head_sha"] = HEX[(HEX.index(snap["head_sha"][0]) + 1) % len(HEX)] * 40
    elif sid == 32: ev["base_sha"] = HEX[(HEX.index(snap["base_sha"][0]) + 1) % len(HEX)] * 40
    elif sid == 33: ev["wu_body_hash"] = "mutated-" + snap["wu_body_hash"]
    elif sid == 34: ev["author"] = rng.choice(ev["material_authors"] + ev["controller_identities"])
    elif sid == 35: ev[rng.choice(["minimal_change_verified", "no_overengineering"])] = False
    elif sid == 36: ev["performance_preserved"] = False
    elif sid == 37: ev["api_semantics_preserved"] = False
    elif sid == 38: ev["diff_proportionate"] = False
    elif sid == 39: ev["deletion_candidates_resolved"] = False
    elif sid == 40: ev["failure_reasons"] = [rng.choice(["OVERENGINEERED", "INTENT_DRIFT", "PERFORMANCE_REGRESSION"])]
    else: raise AssertionError(sid)
    state, reasons = intent_restraint_status(snap)
    assert state == "FAILED" and reasons, (sid, state, reasons)


def run(rounds=1000, seed=0x51A11):
    rng = random.Random(seed); counts = {}; order = list(range(31, 41))
    for _ in range(rounds):
        rng.shuffle(order)
        for sid in order:
            scenario(sid, rng); counts[f"S{sid}"] = counts.get(f"S{sid}", 0) + 1
    return counts


def selftest():
    counts = run(); assert len(counts) == 10; assert all(v == 1000 for v in counts.values())
    print("l5_intent_hostile_sim PASS", counts)


if __name__ == "__main__": selftest()
