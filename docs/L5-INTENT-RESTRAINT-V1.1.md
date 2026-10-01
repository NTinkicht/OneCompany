# L5.1 Engineering Intent & Restraint Gate

## Invariant

Prefer the smallest maintainable correct change that satisfies the frozen work-unit intent while preserving repository conventions, architecture, semantics, and performance.

A green CI run and a technically positive review are necessary but not sufficient for autonomous merge.

## Lifecycle

`IMPLEMENTED -> TESTED -> REVIEWED -> INTENT_RESTRAINT_PENDING -> INTENT_VALIDATED -> MERGE_ELIGIBLE`

A failed attestation yields `INTENT_RESTRAINT_FAILED`. Any remediation creates a new head and invalidates CI, technical review, and the prior intent/restraint attestation.

## Exact-state binding

The structured attestation is bound to `(head_sha, base_sha, wu_body_hash)` and includes independent reviewer identity plus head-bound material-author provenance. The controller must not derive this gate from free-form model prose.

A PASS requires all of the following to be explicitly true: frozen WU contract, intent preservation, scope discipline, minimal-change verification, no overengineering, existing-mechanism reuse or justification, convention preservation, architectural consistency, performance preservation, API/semantic preservation, proportional diff size, adversarial deletion review completion, and resolution of all deletion candidates.

The independent reviewer must explicitly answer the adversarial question: **What code in this PR is technically valid but should nevertheless be removed?**

## Stable failure codes

`INTENT_DRIFT`, `OVERENGINEERED`, `DUPLICATED_MECHANISM`, `PERFORMANCE_REGRESSION`, `SEMANTIC_CHANGE`, `DIFF_DISPROPORTIONATE`, `CONVENTION_DRIFT`, `ARCHITECTURE_DRIFT`, `UNRESOLVED_DELETION_CANDIDATES`, `SELF_REVIEW`, `ATTESTATION_INCOMPLETE`.

## Merge rule

`MERGE_OK_L5_1 := MERGE_OK_BASE AND INTENT_RESTRAINT_OK(exact head, exact base, frozen WU)`.

The pre-lock classifier may temporarily substitute the runtime-only merge-lock/fence fields solely to determine whether a PR is worth acquiring. Immediately before the write, the controller recomputes the complete predicate from a fresh snapshot and real lock/fence evidence.

## Certification

S1-S30 continue to certify coordination, recovery, security, and concurrency. S31-S40 add 10,000 hostile intent/restraint traces, producing a 40,000-trace minimum certification run before unattended activation.
