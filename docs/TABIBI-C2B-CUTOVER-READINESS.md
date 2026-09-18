# Tabibi C2b Cutover Readiness Gate

This document defines the **pre-cutover rehearsal boundary** for Epic 0.6 C2b.

The gate is intentionally non-mutating. It does not install OneCompany into Tabibi, stop schedulers, acquire leases, create branches or pull requests, dispatch product work, publish Team Room authority, or perform a migration. Its only job is to prove whether a separately reviewed cutover could be considered safely.

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

1. **All mutation-capable incumbent writers are quiesced.**
   Each reviewed incumbent record must have `active: false`, a `quiesced_at` timestamp, and a `quiescence_evidence_ref`.

2. **The product stream is at a zero-writer handoff boundary.**
   `cutover.active_stream` must report `status: "quiesced"`, `active_writer_count: 0`, and cite evidence.

3. **Reconciliation happened after quiescence.**
   The exact snapshot SHA and live PR head must be rebound after the final incumbent quiescence event. The manifest must carry a dedicated `reconciliation_completed_at` timestamp and `reconciliation_evidence_ref`; ordering must prove `all quiesced_at <= reconciliation_completed_at <= snapshot.observed_at`. A later snapshot cannot disguise an earlier stale reconciliation.

4. **Post-cutover ownership is single and explicit.**
   Every reviewed mutation capability must map exactly once to the proposed OneCompany writer identity. Ambiguous, partial, or legacy ownership fails closed.

5. **Rollback is ordered and human-controlled.**
   Rollback must disable OneCompany first, restore legacy mutation authority only through a human decision, preserve reviewed ordering, and cite the reviewed rollback evidence.

6. **The human cutover decision is exact-state bound.**
   The approval must be explicit and bind the exact reconciled snapshot SHA and PR head. A prior approval for another head cannot be reused.

## No-dual-writer rule

At no point may OneCompany and the incumbent Tabibi control plane both hold mutation authority for the same capability.

The intended future sequence is:

```text
legacy writers active
        |
        v
C2a shadow analysis
        |
        v
quiesce incumbent mutation paths
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

If any step becomes ambiguous, the safe state is to keep Tabibi unchanged and re-run reconciliation.

## Current Tabibi state

The retained C1/C2a evidence intentionally remains non-ready. It records active incumbent mutation paths, coordination drift, unresolved ownership, and incomplete branch-protection/cutover evidence.

The existence of this gate does not change that state. Before any real C2b mutation, Tabibi must be reconciled live again because its scheduled supervisors and product stream may have advanced since the stored evidence was captured.

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
