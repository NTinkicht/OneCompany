# L5 Post-Claude Cutover Contract

This document records the remaining production-readiness work after the hostile design review and the L5.1 Engineering Intent & Restraint extension.

## Deferred platform enforcement

Repository rulesets / branch protection are intentionally deferred until every other cutover component is complete. Until then, unattended write activation is forbidden. Shadow mode is allowed because it exposes no mutation capability.

`PLATFORM_ENFORCEMENT_DEFERRED` is therefore an expected activation blocker, not an error to bypass.

## 1. Independent reviewer trust boundary

Binding review evidence comes from the human-governed `.l5/trust-policy.json` registry and is enforced by `scripts/l5_trust_boundary.py`. A reviewer must:

- have an exact GitHub login in the binding registry;
- not be a controller identity;
- not be a material author of the exact head under review;
- review the exact current 40-character head SHA and tested base SHA;
- provide a complete, non-skipped, full-diff review with independently verified identity provenance.

The controller cannot create or enlarge the registry at runtime. An unregistered reviewer may provide useful advisory findings but cannot satisfy the binding gate.

The trust boundary is not advisory: `scripts/l5_activation.py` invokes it before authorizing `merge_expected_head`, and the guarded write adapter reproduces activation authorization before mutation. Missing policy, malformed SHA evidence, unregistered/self/material-author review, credential-isolation failure, or policy-hash mismatch therefore fails closed before the merge actuator.

## 2. Credential isolation

A process that executes repository code must never hold a write-capable credential. The production boundary requires all of the following:

- the controller does not execute repository code;
- CI/test workers have no write token in environment or git configuration;
- the write actuator does not execute repository code;
- repository code never runs inside the actuator process;
- the actuator accepts structured, pre-authorized requests only;
- the boundary is explicitly attested before activation.

The L5 candidate workflow is intentionally `contents: read` with checkout credentials disabled. Production mutation remains behind the guarded adapter/actuator path, and the exact credential-boundary evidence is part of final merge authorization.

## 3. API-level hostile simulation

`scripts/l5_api_hostile_sim.py` adds a deterministic-seeded API-level scheduler whose individual traces vary actor ordering, exact heads/bases, stale-read positions, external-change timing, and applicable response faults. It models:

- worker pause/reordering;
- stale reads and force-push ABA;
- partial evidence/pagination;
- dropped responses after a write was applied;
- exact-head/base CAS races;
- lease-epoch reclaim;
- governance or review changes between an earlier observation and final reconcile;
- duplicate writers and merge serialization;
- resource-level exact-state checks even when an API read is stale;
- read-only shadow execution.

A1-A12 run for 1,000 randomized API-level traces each. They supplement the existing S1-S40 certification corpus. The minimum hostile corpus is therefore **52,000 traces total: 40,000 S1-S40 seeded traces plus 12,000 randomized API-level A1-A12 traces**.

## 4. Real-repository shadow mode

`scripts/l5_shadow.py` is structurally read-only: it imports no write adapter and returns `mutation_allowed: false` and `writes: 0`. Before activation, four identical scheduled controllers run this contract at the production cadence. Shadow mode:

- performs fresh reconciliation against all three repositories;
- computes the state-machine decision and exact hypothetical candidate action;
- records why a gate would pass or fail;
- computes a clearly-labelled hypothetical result by staging only the intentionally deferred platform-enforcement fields on a copy of repository evidence;
- never stages away unrelated integrity/governance failures;
- performs zero GitHub mutations;
- never invokes the write adapter.

Shadow output is evidence for cutover readiness but never authorization to mutate.

## 5. Liveness and invariant validation

`scripts/l5_liveness.py` verifies that:

- every run terminates in a named terminal state;
- budget evidence is structurally valid, non-negative, and within retry/review/fix/lease limits;
- a quiet repository is write-free after stabilization;
- an item progresses, waits on a named external condition, or is parked within a bounded number of runs;
- repeated identical non-wait states cannot livelock indefinitely;
- malformed budget or write-count evidence fails closed rather than being ignored.

## 6. Shared control plane

`.l5/control-plane.json` declares `NTinkicht/OneCompany@main` as the shared L5 post-Claude contract for OneCompany, Tabibi, and Veritas Atlas while the controllers are in SHADOW mode. The governed modules are:

- `scripts/l5_trust_boundary.py`
- `scripts/l5_shadow.py`
- `scripts/l5_api_hostile_sim.py`
- `scripts/l5_liveness.py`
- `scripts/l5_activation.py`
- `.l5/trust-policy.json`

Tabibi and Veritas Atlas carry small local manifests that bind them to this reviewed control plane rather than duplicating the trust implementation.

## 7. Final activation sequence

The sequence is fixed:

1. trust boundary and credential isolation merged;
2. A1-A12 API-level hostile simulation green together with S1-S40;
3. four identical production-cadence controllers run read-only shadow mode;
4. shadow/liveness evidence is reviewed and accepted;
5. GitHub platform rulesets / branch protection are installed and independently verified;
6. `GOVERNANCE_DRIFT` / `PLATFORM_ENFORCEMENT_DEFERRED` is human-cleared only after that verification;
7. the same four controllers are switched from SHADOW to ACTIVE without changing the state-machine contract.

Any failure after step 5 returns the affected repository to fail-closed observation-only behavior.
