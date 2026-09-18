# Veritas Atlas C2a Shadow Adoption

Status: **SHADOW ONLY / NOT TARGET-MUTATION READY**

Target: `NTinkicht/veritas-atlas`  
Target main: `e19a0780ec8d5237d923f6d1cdb3a4af24346c95`  
Parent evidence: `source-evidence/veritas-atlas/C1-READONLY-ONBOARDING.md`  
Manifest: `source-evidence/veritas-atlas/c2a-shadow.json`

No change in this workstream is written to Veritas Atlas.

## Purpose

The original shadow-migration analyzer was designed from Tabibi evidence, where an active Work Unit, pull request, PR head, actor registry, actor protocol, and incumbent mutation paths all existed.

Veritas Atlas does not have that shape. C1 observed no open PR and no inherited OneCompany/legacy actor control plane. C2a therefore extends the analyzer without weakening the active-stream checks or inventing synthetic target state.

## Stream modes

### Active

If `live.mode` is missing or equals `active`, the original contract remains in force:

- `work_unit` is required;
- `pr` is required;
- `pr_head` must be an exact 40-character hexadecimal SHA;
- legacy state/work-queue drift remains fail-closed.

This keeps historical Tabibi behavior backward-compatible.

### Idle

`live.mode: "idle"` is allowed only when `live.idle` proves all of the following:

- `verified: true`;
- integer `open_pr_count: 0`;
- integer `active_work_unit_count: 0`;
- non-empty `evidence_ref`;
- `snapshot_sha` exactly equals `snapshot.main_sha`.

An idle declaration also conflicts with any populated `work_unit`, `pr`, or `pr_head` field. Missing evidence is never interpreted as idle.

An idle stream does **not** imply that deployment/runtime mutators are absent. That is a separate incumbent-writer inventory gate.

## Legacy control-plane modes

### Active

Missing `legacy.mode` remains backward-compatible with `active`. Existing registry/protocol actor provenance and drift checks remain unchanged.

### Absent

`legacy.mode: "absent"` requires:

- `control_plane_absence.verified: true`;
- non-empty `evidence_ref`;
- exact `snapshot_sha` binding.

It fails closed if legacy state, work-queue data, or a non-empty registry/protocol actor roster is present.

This means “no legacy control plane” must be evidenced explicitly rather than inferred from missing files.

## Explicit adoption blockers

A manifest may carry `adoption_blockers`. Each valid blocker is added to the analyzer's blocker set; this mechanism can only make readiness stricter, never bypass an existing gate.

Veritas uses it to retain C1 findings that are outside the generic stream/writer model, including CI, tests, health contract, topology, deployment ownership, and production auth/secret boundaries.

## Veritas current shadow state

The current Veritas manifest intentionally reports **not mutation ready**.

The verified facts are narrow:

- target main is bound to `e19a0780ec8d5237d923f6d1cdb3a4af24346c95`;
- GitHub reported zero open PRs during the V-C2a read-only reconciliation;
- the repository has no inherited OneCompany/legacy actor control plane in the C1 topology evidence;
- default branch protection is verified absent.

The following are **not** asserted:

- no external deployment writer;
- no webhook or scheduled external mutator;
- no hosting-provider auto-deploy;
- no database migration automation;
- production-safe auth/secrets;
- protected promotion policy;
- target-native exact-head CI.

Accordingly, the writer inventory is marked incomplete and the C1 blockers are propagated.

## No synthetic state rule

Do not create fake values such as:

- `work_unit: "NONE"`;
- `pr: 0`;
- a fabricated `pr_head`;
- placeholder actor names;
- a claimed empty writer inventory without evidence.

The explicit idle/absent modes exist so those anti-patterns are unnecessary.

## C2b boundary

The generic C2b gate remains separate. A future Veritas cutover must bind human approval and reconciliation to an exact idle-state boundary without fabricating a PR head. If the existing C2b reconciliation contract still requires a PR head for an idle target, it must be extended in a separately reviewed OneCompany change before any cutover can be considered.

C2a does not authorize that change and does not authorize target mutation.

## Governance

- zero additional AI spend;
- target remains read-only;
- no dual writer;
- no candidate/cache authority;
- no human-gate bypass;
- no autonomy self-promotion;
- emergency stop remains sovereign;
- historical Tabibi evidence keeps its original semantics;
- every material target-state change requires fresh reconciliation.
