# L5 Post-Claude Cutover Contract

This document records the remaining production-readiness work after the hostile design review and the L5.1 Engineering Intent & Restraint extension.

## Deferred platform enforcement

Repository rulesets / branch protection are intentionally deferred until every other cutover component is complete. Until then, unattended write activation is forbidden. Shadow mode is allowed because it exposes no mutation capability.

`PLATFORM_ENFORCEMENT_DEFERRED` is therefore an expected activation blocker, not an error to bypass.

## 1. Independent reviewer trust boundary

Binding review evidence must come from `.l5/trust-policy.json`. A reviewer must:

- have an exact GitHub login in the human-governed binding registry;
- not be a controller identity;
- not be a material author of the exact head under review;
- review the exact current head and tested base;
- provide a complete, non-skipped, full-diff review with independently verified identity provenance.

The controller cannot create or enlarge the registry at runtime. An unregistered reviewer may provide useful advisory findings but cannot satisfy the binding gate.

## 2. Credential isolation

A process that executes repository code must never hold a write-capable credential. The production boundary requires all of the following:

- the controller does not execute repository code;
- CI/test workers have no write token in environment or git configuration;
- the write actuator does not execute repository code;
- repository code never runs inside the actuator process;
- the actuator accepts structured, pre-authorized requests only;
- the boundary is explicitly attested before activation.

The existing GitHub CI workflow is intentionally `contents: read` with checkout credentials disabled. Production mutation remains behind the guarded adapter/actuator path.

## 3. API-level hostile simulation

`scripts/l5_post_claude.py` adds an API-level simulator that can model:

- worker pause/reordering;
- stale reads;
- partial evidence/pagination;
- dropped responses after a write was applied;
- exact-head/base CAS races;
- lease epoch reclaim;
- governance or review changes between an earlier observation and final reconcile;
- duplicate writers and merge serialization;
- force-push ABA;
- read-only shadow execution.

A1-A12 run for 1,000 randomized traces each in addition to S1-S40, increasing the minimum hostile certification corpus from 40,000 to 52,000 traces.

## 4. Real-repository shadow mode

Before activation, four identical scheduled controllers run in SHADOW mode at the production cadence. Shadow mode:

- performs fresh reconciliation against all three repositories;
- computes the state-machine decision and exact candidate action;
- records why a gate would pass or fail;
- may compute a clearly-labelled hypothetical result with only the intentionally deferred platform-enforcement fields staged;
- performs zero GitHub mutations;
- never invokes the write adapter.

Shadow output is evidence for cutover readiness but never authorization to mutate.

## 5. Liveness and invariant validation

The liveness checker verifies that:

- every run terminates in a named terminal state;
- retry/review/fix/lease budgets are never exceeded;
- a quiet repository is write-free after stabilization;
- an item progresses, waits on a named external condition, or is parked within a bounded number of runs;
- repeated identical non-wait states cannot livelock indefinitely.

## 6. Final activation sequence

The sequence is fixed:

1. trust boundary and credential isolation merged;
2. A1-A12 API-level hostile simulation green together with S1-S40;
3. four identical production-cadence controllers run read-only shadow mode;
4. shadow/liveness evidence is reviewed and accepted;
5. GitHub platform rulesets / branch protection are installed and independently verified;
6. `GOVERNANCE_DRIFT` / `PLATFORM_ENFORCEMENT_DEFERRED` is human-cleared only after that verification;
7. the same four controllers are switched from SHADOW to ACTIVE without changing the state-machine contract.

Any failure after step 5 returns the affected repository to fail-closed observation-only behavior.
