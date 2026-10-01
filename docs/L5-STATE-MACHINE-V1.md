# L5 State Machine v1.3 - Claude Hostile Contract

This is the deterministic safety contract for four identical peer controllers operating `NTinkicht/Tabibi`, `NTinkicht/OneCompany`, and `NTinkicht/veritas-atlas`.

## Trust boundary

The LLM may diagnose, plan, implement, and triage. It never supplies gate evidence. Gate evidence comes from structured GitHub, CI, security, reviewer, trusted-time, and durable-ledger state. A controller instance is never an independent reviewer.

## Deterministic run machine

Every invocation starts from fresh truth and executes at most one material action:

`BOOT -> HALT_CHECK -> GOVERNANCE_AUDIT -> REPOSITORY_MODE -> INTENT_RECOVERY -> INVENTORY -> CLASSIFY -> SELECT -> ACQUIRE_CAS_LEASE -> RECONCILE_ITEM -> WRITE_INTENT -> FINAL_REVALIDATE -> FENCE_CHECK -> ACTION -> POST_MERGE_VERIFY`

The executable implementation is `scripts/l5_controller.py`. A run never waits in-process for CI or review. WAIT states are reconciled by a later invocation.

## Durable coordination

The authoritative cross-run ledger is `.l5/controller-ledger.json` on `l5/controller-ledger`. Ledger schema v2 stores repository mode, monotonic mode version, full lease/tombstone records, retry budgets, observations, and platform-enforcement evidence. GitHub file/blob SHA is the outer CAS; record version is the inner CAS.

`scripts/l5_ledger_store.py` is the production `CASStore` adapter. Its backend owns GitHub credentials and exposes only ledger read plus exact-blob compare-and-swap. The controller itself remains credential-isolated.

Lease records preserve `holder`, monotonic `epoch`, monotonic `version`, state, observation, expiry, and write-ahead intent. Retirement creates a tombstone; lease history is not deleted or recreated. A PENDING intent cannot be overwritten, deleted, retired, or reassigned before trusted outcome detection resolves it to DONE or ABORTED.

Every invocation has a unique run ID. Lease ownership is dedupe/recovery ownership, never authorization. A lost lease, stale version, changed observation, insufficient expiry margin, stale GitHub blob SHA, or unavailable durable ledger stops the write.

## Repository modes

`NORMAL`, `MERGE_LOCKED`, `MAIN_BROKEN`, `MAIN_BROKEN_ENV`, `AUTOMATION_DEGRADED`, `PROVIDER_THROTTLED`, `GOVERNANCE_DRIFT`, `SECURITY_INTEGRITY_FAILURE`, `CONTROLLER_INTEGRITY`, `HALTED`, `ARCHIVED_PERMISSION_LOST`.

`HALTED`, `CONTROLLER_INTEGRITY`, `SECURITY_INTEGRITY_FAILURE`, and `GOVERNANCE_DRIFT` require human clearance to exit. Missing ledger reachability is `AUTOMATION_DEGRADED`. Missing or weaker platform enforcement is `GOVERNANCE_DRIFT`.

A durable `MERGE_LOCKED` mode is never auto-cleared by a normal governance observation. Only the explicit post-merge verification transition may leave it.

Emergency reverts are not generally exempt from repository modes. A revert may be considered only from the explicit `MAIN_BROKEN` recovery path and remains subject to the existing guarded-write authorization boundary.

## Intent recovery and ambiguous writes

Every external material mutation is preceded by a durable PENDING intent bound to operation, expected head/base, epoch, and idempotency key. On a lost/ambiguous response the intent remains PENDING. A later run performs trusted readback:

- `APPLIED` -> resolve DONE;
- `NOT_APPLIED` -> resolve ABORTED;
- `UNKNOWN` -> remain blocked and do not retry.

No new work begins while an unresolved PENDING intent exists.

A replay result is terminal only when the guarded adapter reports that the effect is already verified complete. A token that is merely already persisted or still awaiting effect verification remains unresolved and must not be converted to DONE.

## Fresh final authorization

Initial classification never authorizes the final write by itself. Immediately before a material mutation the controller must:

1. fetch fresh repository governance evidence;
2. fetch a fresh complete item/PR snapshot;
3. confirm the item identity and exact observation are unchanged;
4. for merges, recompute the full `MERGE_OK` predicate from that fresh snapshot;
5. write the PENDING intent;
6. repeat the fresh item/governance validation;
7. fetch fresh trusted/server time;
8. execute the final lease/resource fence; and
9. call the guarded write adapter.

Reusing the acquisition timestamp at the final fence is forbidden.

## Merge lock and post-merge verification

A merge must acquire the single repository merge-lock lease. Immediately before the write the controller recomputes full `MERGE_OK`, rereads the resource, fetches fresh trusted time, and performs the final fence.

A successful merge resolves its write intent DONE but does **not** release the merge lock. It atomically moves the durable repository mode from `NORMAL` to `MERGE_LOCKED`. A successful authorized revert follows the same containment rule from `MAIN_BROKEN` to `MERGE_LOCKED`.

While `MERGE_LOCKED`, ordinary selection and merge execution are forbidden. The next invocation must identify exactly one `MERGED_UNVERIFIED` item and obtain trusted post-merge health evidence:

- `HEALTHY` -> release the exact merge-lock record, CAS repository mode to `NORMAL`, and mark verification complete;
- `BROKEN` -> release the prior merge-lock record, CAS repository mode to `MAIN_BROKEN`, and allow only the bounded recovery path on a later invocation;
- `ENV_BROKEN` -> release the prior merge-lock record, CAS repository mode to `MAIN_BROKEN_ENV`, and do not infer a code regression;
- `UNKNOWN` -> retain `MERGE_LOCKED` and do nothing.

If lock evidence is missing, stale, nonterminal, or there is not exactly one merged-unverified item, remain fail-closed. No second merge may start before this transition completes, even if the original lease TTL has elapsed.

## Capacity slots

Replenishment requires a numbered `CAPACITY_SLOT_n` lease before a new stream may start. Simultaneous controllers competing for the same empty slot must produce exactly one winner. A reservation is a controller action; the selected work becomes eligible for a subsequent invocation. Expired reservations may be reclaimed only with a higher lease epoch.

## Full MERGE_OK

Autonomous merge requires every datum to be explicitly known and valid, including:

- repository mode NORMAL and owned repo merge lock;
- exact expected head and exact tested base;
- exact current PR/head/base/ref state and clean mergeability;
- pinned live governance at least as strong as pinned policy;
- branch protection or active ruleset enforcement;
- complete file enumeration and bounded diff;
- governed-path and test-weakening checks clean;
- controller/adapter hashes valid;
- credential isolation and secret hygiene clean;
- required CI and security checks from the exact pinned app/workflow sources;
- complete attempt-history evidence and `assertion_failure_any_attempt == false` for every required check;
- no rerun-to-green authorization after an assertion failure on the same head;
- complete fresh independent non-material-author review bound to exact head and base;
- head-bound complete material-author provenance and reviewer eligibility;
- no unresolved findings, required threads, security alerts, human holds, or dependency blockers;
- controller is neither admin nor bypass actor;
- valid pending merge intent and final fence.

Unknown, null, stale, truncated, contradictory, inaccessible, skipped, 403, 5xx, or source-mismatched evidence is never PASS. Merge-queue status does not waive exact tested-base identity.

## Budgets and findings

CI infrastructure reruns are bounded to 2 per head/check, fix iterations to 5, review rounds to 3, and lease acquisitions to 12. Exhaustion produces `PARKED`; gates are never lowered. A disputed review finding is `DISPUTED_FINDING` and cannot be self-dismissed by a controller.

## Certification

Before activation the candidate CI runs unit/controller/ledger/durable-store regressions and Claude scenarios S1-S30 with 1,000 randomized traces per scenario (30,000 traces total). The simulations specifically attack stale leases, dropped responses, pending-intent replacement, ABA/reclaim, exact-head/base review and CI evidence, governance drift, credential boundaries, merge locks, capacity races, stale observations, security failures, idle queues, budget exhaustion, ledger loss, controller integrity, delayed final fences, replay ambiguity, and post-merge containment.

Passing simulation is necessary but not sufficient: full repository CI and a fresh independent exact-head review must also pass.

## Governed-path and activation policy

Changes to this controller, ledger contract, durable store, candidate workflow, or other governed enforcement paths are human-merge-only. They cannot be autonomously merged by the controller they modify.

Unattended activation additionally requires verified platform enforcement on `main`, human clearance of `GOVERNANCE_DRIFT`, successful shadow-mode execution, and four identical scheduled controllers executing this exact contract. Staggering is load distribution only and is never mutual exclusion.
