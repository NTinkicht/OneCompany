# L5 State Machine v1.1 - Claude Hostile Contract

This is the deterministic safety contract for four identical peer controllers operating `NTinkicht/Tabibi`, `NTinkicht/OneCompany`, and `NTinkicht/veritas-atlas`.

## Trust boundary
The LLM may diagnose, plan, implement, repair, and triage. It never supplies gate evidence. Gate evidence comes only from structured GitHub, CI, security, reviewer, and controller-ledger state. A controller instance never qualifies as its own independent reviewer.

## Run machine
`BOOT -> HALT_CHECK -> GOVERNANCE_AUDIT -> REPOSITORY_MODE -> INTENT_RECOVERY -> INVENTORY -> CLASSIFY -> SELECT -> ACQUIRE_CAS_LEASE -> RECONCILE_ITEM -> WRITE_INTENT -> FENCE_CHECK -> ACTION`

Every invocation has a unique run ID and reconstructs truth from live evidence. No previous execution position is trusted. A run never waits for CI or review; it exits into a named WAIT state and a later invocation reconciles from scratch.

## Durable controller ledger
Authoritative cross-run coordination state is stored at `.l5/controller-ledger.json` on branch `l5/controller-ledger`. Writers must read the current blob SHA and use that exact SHA as the GitHub Contents update precondition. Document revision, lease version, budget version, mode version, and lease epoch are monotonic. A stale CAS loses and performs no write.

The ledger contains repository mode, leases/intents, shared budgets, and observations. If the ledger is unreadable or contradictory, the repository enters `AUTOMATION_DEGRADED` and no dangerous autonomous write is allowed.

## Coordination and fencing
Leases are ownership/deduplication, never authorization. Each material write requires a live lease, monotonically increasing epoch, PENDING write-ahead intent, unchanged observed head/base/WU identity, sufficient TTL, and a resource-level expected ref/SHA where GitHub supports one. Expired leases with PENDING intents enter `INTENT_RECOVERY` before reassignment. Ambiguous write responses are read back by detection key before any retry.

A repo-wide `REPO_MERGE_LOCK` permits at most one merge in flight. It remains held through post-merge verification. Replenishment requires a numbered `CAPACITY_SLOT_n` lease so concurrent controllers cannot overshoot WIP.

## Derived PR states
`GOVERNANCE_CHANGE`, `WAIT_CI`, `CI_MISSING`, `CI_RED_INFRA`, `CI_RED_DETERMINISTIC`, `BEHIND_BASE`, `CI_GREEN_UNREVIEWED`, `FINDINGS_OPEN`, `DISPUTED_FINDING`, `BLOCK_HUMAN`, `WAIT_DEPENDENCY`, `MERGE_ELIGIBLE`, `MERGE_QUEUED`, `MERGE_OUTCOME_UNKNOWN`, `MERGED_UNVERIFIED`, `MERGED_VERIFIED`, `MAIN_BROKEN`, `REVERT_PENDING`, `SUPERSEDED`, `PARKED`, `WAIT_PROVIDER`, `IMPLEMENT`, `IDLE`.

States are derived from live evidence plus the ledger and are not persisted as workflow position.

## Repository modes
`NORMAL`, `MERGE_LOCKED`, `MAIN_BROKEN`, `MAIN_BROKEN_ENV`, `AUTOMATION_DEGRADED`, `PROVIDER_THROTTLED`, `GOVERNANCE_DRIFT`, `SECURITY_INTEGRITY_FAILURE`, `CONTROLLER_INTEGRITY`, `HALTED`, `ARCHIVED_PERMISSION_LOST`.

`HALTED`, `CONTROLLER_INTEGRITY`, `SECURITY_INTEGRITY_FAILURE`, and `GOVERNANCE_DRIFT` require human clearance. Main that lacks qualifying branch protection/ruleset enforcement is `GOVERNANCE_DRIFT`.

## MERGE_OK
Autonomous merge is allowed only when a single fresh snapshot proves all clauses true:
- repository mode is `NORMAL`, repo merge lock is owned, fence is valid, and no unrelated unresolved intent exists;
- PR is open, non-draft, same-repo, correct base, exact API/ref head/base, base-current or queued, clean and mergeable;
- live requirements are at least pinned requirements, protection/rulesets are active, controller is neither admin nor bypass actor;
- complete file enumeration proves no governed-path change or test weakening; diff/controller/adapter hashes are within pinned policy;
- every required CI and security source is pinned by app ID plus workflow path, is exact-head, tested against the current base/queue base, latest-attempt success, and has no assertion failure on any attempt for that head;
- code scanning is present with no new disallowed alert and no secret finding;
- a complete non-skipped full-diff independent review covers the exact head/base and reviewer is neither a material author nor controller identity; no later undismissed change request exists;
- all findings are independently/human-confirmed closed, thread-resolution policy holds, no required thread/human hold remains, dependencies are verified;
- credential isolation and controller-authored secret hygiene are proven.

Unknown, null, truncated, partial, stale, contradictory, inaccessible, 403, 5xx, timeout, skipped, or unpinned evidence is never PASS. A check that assertion-failed on head H cannot become merge evidence merely by rerunning green on the same H.

## Review and findings
The controller performs TRIAGE, never binding review. A believed-invalid finding enters `DISPUTED_FINDING`; the controller does not self-close it. Human threads are never auto-resolved. A fresh head invalidates old review evidence.

## Budgets
CI infrastructure reruns: max 2 per head/check. Fix iterations: max 5. Review rounds: max 3. Lease acquisitions are bounded. Exhaustion enters `PARKED`; gates are never lowered.

## Post-merge
Merge uses expected-head protection. Ambiguous merge response becomes `MERGE_OUTCOME_UNKNOWN` and is read back on the next run. A successful merge becomes `MERGED_UNVERIFIED` while the repo remains `MERGE_LOCKED`. Only verified healthy main releases the lock and dependency/capacity slot. A regression attributable to the merge enters `MAIN_BROKEN`; environmental failure enters `MAIN_BROKEN_ENV`.

## Certification and activation
Release certification runs Claude scenarios S1-S30 with at least 1,000 traces per scenario. Shadow mode follows certification. Only after certification, shadow mode, active platform enforcement, human clearance of `GOVERNANCE_DRIFT`, and human merge of governed controller/workflow changes may the four 15-minute scheduled controllers be enabled. All four execute this exact contract; staggering distributes load and is never mutual exclusion.
