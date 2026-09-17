# Epic 0.7 - Execution Core

## Objective

Add a native, dependency-free execution-control layer beneath OneCompany's existing Work Unit lease and governance model. The layer must improve bounded execution reliability without creating a second authority plane.

Integration branch: `epic-0.7-execution-core-integration`

Promotion target: `main` only after exact-head CI, assurance, review, and normal protected-branch requirements are satisfied.

## Non-negotiable boundaries

- OneCompany remains the authority for WU admission, leases, routing eligibility, independent review, exact-head/base gates, and merge.
- Execution Core cannot expand WU scope or grant itself authority.
- Runtime state is unversioned local execution state, not planning truth.
- Completion claims are not evidence.
- Budget/stall failover recommendations cannot transfer a lease by themselves.
- External runtime adapters receive bounded requests and no implicit authority.

## Work Units

### WU1 - RunContext and generation fencing

Deliver persistent execution identity using `wu_id`, `run_id`, and `generation`. Reject stale state mutations. Objective revision/failover can rotate the generation.

Acceptance:
- stale generation mutation fails closed;
- context is JSON serializable and recoverable;
- runtime state is ignored by Git.

### WU2 - TransitionEngine

Deliver a deterministic, copy-based execution state transition engine with caller-injected time and no I/O side effects.

Acceptance:
- pause/resume/block/unblock/budget-limit/generation rotation are validated;
- input context is not mutated;
- illegal transitions fail closed.

### WU3 - ExecutionJournal

Deliver append-only execution event evidence with state hashes and chained record hashes.

Acceptance:
- monotonic sequence;
- previous-hash chaining;
- tamper detection;
- atomic current-state persistence remains separate from the journal.

### WU4 - ObjectiveTracker and TaskBoard

Deliver durable bounded objectives/acceptance criteria plus tactical task tracking.

Acceptance:
- objective edits rotate generation;
- tactical task changes require the current generation;
- task completion is not treated as acceptance evidence.

### WU5 - EvidenceRegistry

Deliver evidence-to-acceptance-criterion mapping plus bounded decision/evidence/dead-end lessons.

Acceptance:
- unknown AC references fail closed;
- evidence explicitly records whether it is authoritative;
- bounded lessons preserve useful execution context without unbounded growth.

### WU6 - ProgressSentinel

Deliver substantive-progress fingerprinting independent of heartbeat/activity signals.

Acceptance fingerprint includes:
- HEAD;
- unmet ACs;
- tests;
- blockers;
- evidence IDs;
- material changes.

Repeated unchanged fingerprints trigger the configured stall threshold.

### WU7 - ResourceGuard

Deliver per-run bounded execution limits.

Acceptance:
- assistant-token ceiling;
- active-time ceiling;
- consecutive-error ceiling;
- unchanged-progress ceiling;
- exhaustion never changes global budget policy or silently enables paid fallback.

### WU8 - CompletionGate

Deliver deterministic evidence preflight plus an externally supplied evaluator verdict contract.

Acceptance:
- worker claim alone cannot complete the run;
- every AC requires authoritative evidence;
- blocked/unfinished tasks prevent `met`;
- evaluator cannot override missing evidence;
- `met` completes only the execution session and does not bypass OneCompany CI/review/merge governance.

### WU9 - Worker role/tier execution metadata

Deliver advisory execution profiles separate from hard OneCompany routing eligibility.

Acceptance:
- role metadata;
- light/standard/heavy tiers;
- preferred complexity;
- cost class;
- deterministic ranking constrained to caller-supplied allowed cost classes.

### WU10 - AgentRuntimeAdapter

Deliver a generic dependency-free boundary for external worker runtimes.

Acceptance:
- explicit argv;
- `shell=False`;
- bounded timeout;
- JSON stdin envelope;
- environment allowlist;
- RunKey included in every request;
- adapter carries no implicit lease/review/merge authority.

### WU11 - Supervisor/no-idle integration

Deliver execution-level supervisor recommendations that distinguish progress from activity.

Acceptance:
- healthy execution -> continue;
- budget exhaustion -> pause-budget recommendation;
- repeated errors -> remediate/failover recommendation;
- unchanged progress -> reconcile/failover recommendation requiring a new generation;
- blocked work -> explicit blocker escalation;
- supervisor never transfers the canonical WU lease itself.

### WU12 - Adversarial/end-to-end self-tests

Deliver regression coverage across the Execution Core.

Acceptance includes:
- stale generation rejection;
- evidence-gated completion;
- non-authoritative worker claims rejected;
- stall detection and recovery;
- resource bounds;
- pure transition behavior;
- persistence and hash-chain verification;
- journal tamper rejection;
- complexity-aware worker ranking;
- safe external-runtime invocation;
- bounded durable lessons.

## Promotion gate

Before promotion to `main`:

1. branch compiles;
2. Execution Core self-tests pass;
3. repository schema/governance validation passes;
4. exact branch-head CI passes;
5. actionable review findings are resolved;
6. integration branch is reconciled against current `main`;
7. final PR targets protected `main`;
8. merge follows existing OneCompany authority and branch-protection rules.
