# L5 State Machine v1.2 - Claude Hostile Contract

This is the deterministic safety contract for four identical peer controllers operating `NTinkicht/Tabibi`, `NTinkicht/OneCompany`, and `NTinkicht/veritas-atlas`.

## Trust boundary

The LLM may diagnose, plan, implement, and triage. It never supplies gate evidence. Gate evidence comes from structured GitHub, CI, security, reviewer, and durable-ledger state. A controller instance is never an independent reviewer.

## Deterministic run machine

Every invocation starts from fresh truth and executes at most one material action:

`BOOT -> HALT_CHECK -> GOVERNANCE_AUDIT -> REPOSITORY_MODE -> INTENT_RECOVERY -> INVENTORY -> CLASSIFY -> SELECT -> ACQUIRE_CAS_LEASE -> RECONCILE_ITEM -> WRITE_INTENT -> FENCE_CHECK -> ACTION`

The executable implementation is `scripts/l5_controller.py`. A run never waits in-process for CI or review. WAIT states are reconciled by a later invocation.

## Durable coordination

The authoritative cross-run ledger is `.l5/controller-ledger.json` on `l5/controller-ledger`. Ledger schema v2 stores repository mode, monotonic mode version, full lease/tombstone records, retry budgets, observations, and platform-enforcement evidence. GitHub file/blob SHA is the outer CAS; record version is the inner CAS.

Lease records preserve `holder`, monotonic `epoch`, monotonic `version`, `active`, observation, expiry, and write-ahead intent. Retirement creates a tombstone; lease history is not deleted or recreated. A PENDING intent cannot be overwritten, deleted, retired, or reassigned before trusted outcome detection resolves it to DONE or ABORTED.

Every invocation has a unique run ID. Lease ownership is dedupe/recovery ownership, never authorization. A lost lease, stale version, changed observation, insufficient expiry margin, or stale GitHub blob SHA stops the write.

## Repository modes

`NORMAL`, `MERGE_LOCKED`, `MAIN_BROKEN`, `MAIN_BROKEN_ENV`, `AUTOMATION_DEGRADED`, `PROVIDER_THROTTLED`, `GOVERNANCE_DRIFT`, `SECURITY_INTEGRITY_FAILURE`, `CONTROLLER_INTEGRITY`, `HALTED`, `ARCHIVED_PERMISSION_LOST`.

`HALTED`, `CONTROLLER_INTEGRITY`, `SECURITY_INTEGRITY_FAILURE`, and `GOVERNANCE_DRIFT` require human clearance to exit. Missing ledger reachability is `AUTOMATION_DEGRADED`. Missing or weaker platform enforcement is `GOVERNANCE_DRIFT`.

Emergency reverts are not generally exempt from repository modes. A revert may be fenced outside NORMAL only for `MAIN_BROKEN` or `MAIN_BROKEN_ENV` and only with explicit trusted emergency-revert authority.

## Intent recovery and ambiguous writes

Every external material mutation is preceded by a durable PENDING intent bound to operation, expected head/base, epoch, and idempotency key. On a lost/ambiguous response the intent remains PENDING. A later run performs trusted readback:

- `APPLIED` -> resolve DONE;
- `NOT_APPLIED` -> resolve ABORTED;
- `UNKNOWN` -> remain blocked and do not retry.

No new work begins while an unresolved PENDING intent exists.

## Merge lock

A merge must acquire the single repository merge-lock lease. Immediately before the write the controller recomputes full `MERGE_OK`, rereads the resource, and performs the final fence. A successful merge resolves its intent DONE but keeps the merge lock active and moves the durable repository mode to `MERGE_LOCKED`.

The merge lock is released only after exactly one merged-unverified item is identified and post-merge main health is `HEALTHY`. If main is broken, the repository transitions to `MAIN_BROKEN` and the lock is not treated as a successful verification. No second merge may start while the merge lock is active.

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
- `assertion_history_complete == true` and `assertion_failure_any_attempt == false` for every required check;
- no rerun-to-green authorization after an assertion failure on the same head;
- complete fresh independent non-material-author review bound to exact head and base;
- no unresolved findings, required threads, security alerts, human holds, or dependency blockers;
- controller is neither admin nor bypass actor;
- valid pending merge intent and final fence.

Unknown, null, stale, truncated, contradictory, inaccessible, skipped, 403, 5xx, or source-mismatched evidence is never PASS. Merge-queue status does not waive exact tested-base identity.

## Budgets and findings

CI infrastructure reruns are bounded to 2 per head/check, fix iterations to 5, review rounds to 3, and lease acquisitions to 12. Exhaustion produces `PARKED`; gates are never lowered. A disputed review finding is `DISPUTED_FINDING` and cannot be self-dismissed by a controller.

## Certification

Before activation the candidate CI runs unit/controller/ledger regressions and Claude scenarios S1-S30 with 1,000 deterministic randomized traces per scenario (30,000 traces total). The simulations specifically attack stale leases, dropped responses, pending-intent replacement, ABA/reclaim, exact-head/base review and CI evidence, governance drift, credential boundaries, merge locks, capacity races, stale observations, security failures, idle queues, budget exhaustion, ledger loss, and controller integrity.

Passing simulation is necessary but not sufficient: full repository CI and a fresh independent exact-head review must also pass.

## Governed-path and activation policy

Changes to this controller, ledger contract, candidate workflow, or other governed enforcement paths are human-merge-only. They cannot be autonomously merged by the controller they modify.

Unattended activation additionally requires verified platform enforcement on `main`, human clearance of `GOVERNANCE_DRIFT`, successful shadow-mode execution, and four identical scheduled controllers executing this exact contract. Staggering is load distribution only and is never mutual exclusion.
