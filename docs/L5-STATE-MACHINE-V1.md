# L5 State Machine v1.0

This is the deterministic safety contract for four identical peer controllers operating Tabibi, OneCompany, and veritas-atlas.

## Trust boundary

The LLM diagnoses, plans, implements and triages. It never supplies gate evidence. Gate evidence comes from structured GitHub/CI/security/reviewer state and is evaluated deterministically. Independent review is CodeRabbit or an authorized human; no controller instance qualifies as an independent reviewer.

## Run machine

`BOOT -> HALT_CHECK -> GOVERNANCE_AUDIT -> REPOSITORY_MODE -> INTENT_RECOVERY -> INVENTORY -> CLASSIFY -> SELECT -> ACQUIRE_CAS_LEASE -> RECONCILE_ITEM -> WRITE_INTENT -> FENCE_CHECK -> ACTION`

Every run reconstructs truth. No previous execution position is trusted. A run never waits for CI or review; it exits the item into a WAIT state and a later run reconciles it.

## Action lanes

- IMPLEMENT/REPAIR -> expected-ref push -> WAIT_CI.
- CI: pending -> WAIT_CI; infrastructure failure -> bounded rerun; deterministic failure -> REPAIR; exact-state green -> one independent-review request -> WAIT_INDEPENDENT_REVIEW.
- REVIEW: unavailable -> WAIT_PROVIDER; valid finding -> REPAIR; disputed -> DISPUTED_FINDING; human finding -> BLOCK_HUMAN; independent exact-head pass -> MERGE lane.
- MERGE: acquire repo merge lock -> recompute full MERGE_OK -> write merge intent -> final fence -> expected-head merge/queue -> MERGED_UNVERIFIED -> MERGE_LOCKED -> post-merge main CI -> MERGED_VERIFIED or MAIN_BROKEN.

## Fail closed

Unknown, null, truncated, stale, inaccessible, contradictory, 403, 5xx or ambiguous gate evidence is never PASS. A timeout after a write is outcome-unknown: read the operation detection key before any retry.

## Coordination

Leases are dedupe/recovery ownership, not authorization. Each invocation has a unique run ID. Lease epochs are monotonic. Every material write has a PENDING write-ahead intent. Dangerous operations require a resource-level expected SHA/ref precondition. A lost lease or changed observation stops writes immediately.

Only one merge may be in flight per repository. A repository remains MERGE_LOCKED until post-merge health is established.

## Governance

Effective requirements are monotone: pinned policy union live requirements. Live policy may add requirements but cannot remove pinned requirements. Any weakening is GOVERNANCE_DRIFT. Any PR touching a governed path or weakening tests is human-only and cannot be autonomously merged.

## Repository modes

NORMAL, MERGE_LOCKED, MAIN_BROKEN, MAIN_BROKEN_ENV, AUTOMATION_DEGRADED, PROVIDER_THROTTLED, GOVERNANCE_DRIFT, SECURITY_INTEGRITY_FAILURE, CONTROLLER_INTEGRITY, HALTED.

HALTED, CONTROLLER_INTEGRITY, SECURITY_INTEGRITY_FAILURE and GOVERNANCE_DRIFT require human clearance.

## Merge invariant

Autonomous merge requires all of: NORMAL mode; valid fence and pending intent; exact expected head and tested base; all mandatory CI/security checks conclude success from pinned sources; governance unchanged; no governed-path/test weakening; fresh external independent review on the exact head by a non-material author; no unresolved confirmed finding/required thread/human hold; dependencies verified; repo merge lock owned; controller is not admin/bypass; every required datum known.

The merge call must carry expected-head protection. Ambiguous merge responses are never retried in the same run.

## Budgets

Review request: once per PR/head per cooldown. CI infrastructure reruns: max 2 per head/check. Fix iterations: max 5. Review rounds: max 3. Exhaustion parks the item rather than lowering a gate.

## Deployment gate

Before unattended activation: run adversarial coordination/security/recovery simulations, then shadow mode. The four scheduled tasks must execute this exact contract; stagger is for load distribution only and is never mutual exclusion.
