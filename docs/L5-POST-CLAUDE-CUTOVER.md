# L5 Post-Claude Cutover Contract

This document records the production-readiness contract after the hostile design review and the L5.1 Engineering Intent & Restraint extension.

## Platform enforcement and activation boundary

Repository rulesets are now installed and independently verifiable on OneCompany, Tabibi, and Veritas Atlas. The controller remains in **LIVE_SAFE** until a separate protected activation change records fresh enforcement evidence, clears the durable `GOVERNANCE_DRIFT` ledgers with the owner-authorized CAS transition, pins an immutable certified control-plane revision, and binds ACTIVE execution to byte-identical certified runtime files.

LIVE_SAFE continues to allow reversible feature-branch, PR, CI, review, issue and work-unit mutations. Main-changing operations remain blocked until final activation. A candidate activation change cannot use its own policy relaxation to approve itself.

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
- read-only shadow diagnostics.

A1-A12 run for 1,000 randomized API-level traces each. They supplement the existing S1-S40 certification corpus. The minimum hostile corpus is therefore **52,000 traces total: 40,000 S1-S40 seeded traces plus 12,000 randomized API-level A1-A12 traces**.

A11 specifically verifies exact-head ABA behavior after review revocation: the head returns to the originally observed SHA, but the final gate must still reject the merge because review evidence is no longer valid.

## 4. LIVE_SAFE real-repository validation

The four identical scheduled controllers run at :00, :15, :30 and :45. In LIVE_SAFE mode they may perform reversible engineering writes such as canonical feature-branch commits, PR creation and updates, CI reruns, eligible independent review requests, comments/labels, verified thread resolution and dependency-ready work-unit replenishment.

They must still reconcile fresh repository truth, exact head/base, source-pinned CI, reviewer identity and material-author separation, L5.1 intent/restraint evidence, budgets, lease/intent state, credential isolation and all human-only boundaries before acting.

Main-changing actions remain blocked before final activation: no PR merge/enqueue, no direct push to `main`, no default-branch history rewrite and no weakening of CI/review/security controls.

`scripts/l5_shadow.py` remains available as a strictly read-only diagnostic oracle that returns `mutation_allowed: false` and `writes: 0` for comparison and fault simulation.

## 5. Liveness and invariant validation

`scripts/l5_liveness.py` verifies that:

- every run terminates in a named terminal state;
- budget evidence is structurally valid, non-negative, and within retry/review/fix/lease limits;
- a quiet repository is write-free after stabilization;
- an item progresses, waits on a named external condition, or is parked within a bounded number of runs;
- repeated identical non-wait states cannot livelock indefinitely;
- malformed budget or write-count evidence fails closed rather than being ignored.

## 6. Shared control plane and runtime pin

`.l5/control-plane.json` declares `NTinkicht/OneCompany` as the shared L5 contract for OneCompany, Tabibi, and Veritas Atlas. The governed modules are:

- `scripts/l5_trust_boundary.py`
- `scripts/l5_shadow.py`
- `scripts/l5_api_hostile_sim.py`
- `scripts/l5_liveness.py`
- `scripts/l5_activation.py`
- `.l5/trust-policy.json`

Before ACTIVE authorization, `scripts/l5_control_plane.py` additionally requires a complete SHA-256 map for the certified runtime files and verifies the local runtime bytes against it. The digest map is derived from the immutable `control_ref` certification revision and is itself protected by base governance. A modified or missing runtime file therefore fails closed even if the manifest still contains a syntactically valid commit SHA.

Tabibi and Veritas Atlas carry local manifests that bind them to the same reviewed OneCompany control plane rather than independently redefining the trust implementation.

## 7. Final activation sequence

The required sequence is:

1. trust boundary and credential isolation merged;
2. A1-A12 API-level hostile simulation green together with S1-S40;
3. four identical production-cadence controllers exercise reversible writes in LIVE_SAFE;
4. live platform rulesets are installed and independently re-verified on all managed repositories;
5. base governance protects the activation manifest and critical L5 runtime from ordinary merge authority;
6. ACTIVE authorization is bound to runtime SHA-256 evidence derived from an immutable certified OneCompany revision;
7. the owner-authorized `GOVERNANCE_DRIFT` ledger exit is applied with revision, mode-version, and storage blob-SHA CAS checks for each repository;
8. a separate activation PR updates the contract text and manifest to ACTIVE/VERIFIED, receives current independent review and required CI, and merges through protected main;
9. downstream manifests pin the resulting certified OneCompany revision and repeat the protected activation transition.

Until step 8 completes, non-main validation continues rather than idling.
