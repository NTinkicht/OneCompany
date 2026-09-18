# Target C2b Cutover Readiness Gate

This document defines the **pre-cutover rehearsal boundary** for Epic 0.6 C2b.

The gate is deliberately target-agnostic and non-mutating. It does not install OneCompany into a target repository, stop schedulers, acquire leases, create target branches or pull requests, dispatch product work, publish target authority, or perform a migration. Its only job is to prove whether a separately reviewed cutover could be considered safely.

Veritas Atlas (`NTinkicht/veritas-atlas`) is the first active proving-ground target. Historical Tabibi C1/C2a evidence remains valid only for its original provenance and regression coverage; it is not reused as Veritas evidence.

## Command

```bash
python onecompany.py cutover-readiness --manifest <manifest.json>
python onecompany.py cutover-readiness --manifest <manifest.json> --json
```

Exit codes:

- `0` - all readiness conditions, including the explicit human cutover decision, are present;
- `3` - readiness is blocked;
- `2` - the manifest could not be read or parsed.

Even when the command exits `0`, the report always contains:

```json
{
  "target_mutated": false,
  "mutation_authorized": false,
  "authority_effects": []
}
```

A green readiness report therefore **does not authorize a cutover**. The actual target-specific migration must be a separate reviewed change.

## Required boundary

C2b readiness is layered on top of C2a shadow readiness. If the C2a report is blocked, C2b is blocked automatically.

The rehearsal additionally requires all of the following:

1. **All mutation-capable incumbent writers are explicit and quiesced.**
   Each mutation-capable incumbent must declare at least one explicit capability, and each reviewed incumbent record must have `active: false`, a `quiesced_at` timestamp, and a `quiescence_evidence_ref`. A capabilityless mutation writer fails closed because ownership cannot be proven. A target believed to have no incumbent mutators must prove inventory completeness rather than silently assuming an empty set.

2. **The product stream is at a timestamped zero-writer handoff boundary.**
   `cutover.active_stream` must report `status: "quiesced"`, an integer (not boolean) `active_writer_count: 0`, cite evidence, and include a timezone-aware `quiesced_at` timestamp.

3. **Reconciliation happened after quiescence and is bound to the exact stream identity.**
   All chronology timestamps must be timezone-aware and the exact snapshot SHA must be rebound after the final incumbent and stream quiescence event. For an active target, reconciliation must bind the exact live PR head. For a verified-idle target, no PR head is fabricated: reconciliation must instead bind the exact snapshot `observed_at` and shared `observation_boundary_ref`, and `reconciliation_pr_head` must be absent. The manifest must carry a dedicated `reconciliation_completed_at` timestamp and `reconciliation_evidence_ref`; ordering must prove both `all incumbent.quiesced_at <= reconciliation_completed_at` and `active_stream.quiesced_at <= reconciliation_completed_at <= snapshot.observed_at`.

4. **Post-cutover ownership is single and explicit.**
   Every mutation-capable incumbent record must itself be reviewed. Every reviewed mutation capability must map exactly once to a proposed OneCompany writer identity that carries reviewed identity/capability evidence. Ambiguous, partial, unreviewed, or legacy ownership fails closed.

5. **Rollback is ordered and human-controlled.**
   Rollback must disable OneCompany first, restore legacy mutation authority only through a human decision, preserve reviewed ordering, and cite reviewed rollback evidence.

6. **The human cutover decision is exact-state, principal-evidence, and reconciliation-evidence bound.**
   The approval must be explicit and carry a structured `principal_evidence` object whose `identity` exactly matches the declared `approver_identity`, whose `principal_type` is `human`, whose `verified` flag is true, and whose `evidence_ref` is non-empty. It must be timestamped after the post-quiescence reconciliation and observed snapshot and reference that exact reconciliation evidence record. Active targets bind approval to the exact snapshot SHA and PR head. Verified-idle targets bind approval to the exact snapshot SHA, `observed_at`, and shared `observation_boundary_ref`, with no synthetic approved PR head. A bot/service account, mismatched principal, missing evidence object, or prior approval for an older operational state fails closed.

### Verified-idle targets

A verified-idle target is not inferred from missing PR fields. C2a must already have independently proven `live.mode: "idle"` with zero open PRs/work and exact observation-boundary evidence. C2b then reuses that boundary for reconciliation and human approval. Populating a fake PR head to satisfy the cutover gate is forbidden and fails closed through the C2a stream-conflict checks.

## No-dual-writer rule

At no point may OneCompany and an incumbent target control plane both hold mutation authority for the same capability.

The intended sequence is:

```text
read-only target onboarding
        |
        v
C2a shadow analysis
        |
        v
prove/quiesce incumbent mutation paths
        |
        v
fresh exact-state reconciliation
        |
        v
C2b readiness gate
        |
        v
explicit human cutover decision
        |
        v
separately reviewed target-specific cutover
        |
        v
OneCompany becomes the single canonical owner
```

If any step becomes ambiguous, the safe state is to keep the target unchanged and re-run reconciliation.

## First active target: Veritas Atlas

Veritas Atlas must receive fresh C1 read-only onboarding and C2a shadow evidence before this gate can support a real cutover decision. The current pivot does not mutate Veritas Atlas and does not inherit target facts from Tabibi.

The initial read-only baseline has already identified important items that must remain blockers until independently resolved: unprotected `main`, no observed GitHub Actions workflow estate, local-only documented smoke tests, and unknown deployment/runtime mutators.

## Historical Tabibi evidence

Existing Tabibi C1/C2a evidence is preserved as historical provenance and fail-closed regression coverage. Tabibi remains under its existing control plane. This target-neutral gate does not stop its schedules, change its writers, or reinterpret its stored state.

## Governance invariants

C2b preserves the existing OneCompany constraints:

- zero additional AI spend;
- no PAYG/overage/credits/top-ups/OpenRouter/Vertex fallback;
- no candidate/cache state as authority;
- no AI/bot satisfaction of a required human Code Owner or cutover decision;
- no autonomy self-promotion;
- no branch-protection/reviewer-independence weakening;
- emergency stop remains sovereign;
- no duplicate writer;
- readiness evidence is exact-state bound and must be revalidated after material change.
