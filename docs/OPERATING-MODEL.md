# Operating Model

## The company heartbeat

OneCompany repeatedly executes one control loop:

1. **Observe** — fetch live GitHub state and capacity signals.
2. **Reconcile** — repair stale declared state before acting.
3. **Prioritize** — choose the smallest dependency-ready Work Unit with highest policy priority.
4. **Route** — find an eligible actor for the required capability.
5. **Lease** — grant exclusive implementation authority for the canonical stream.
6. **Execute** — produce a bounded artifact: commit, PR update, test, review, or documented decision.
7. **Verify** — run deterministic CI.
8. **Review** — obtain independent exact-head judgment where required.
9. **Merge** — only the gated SHA, only if policy permits.
10. **Reconcile again** — close WU, release lease, update derived state.
11. **Continue** — if ready work remains and autonomy allows, immediately select the next unit.

## Actor status is not work status

An agent saying “I’m on it” is not evidence that a Work Unit is progressing. Evidence is a durable artifact or verifiable execution state:

- commit pushed;
- branch head changed;
- PR opened/updated;
- CI running;
- review posted for current SHA;
- issue/state transition recorded;
- reproducible analysis attached.

A no-idle system watches **work artifacts**, not conversational acknowledgements.

## Operational states

Recommended company-level states:

- `ACTIVE_IMPLEMENTATION`
- `WAITING_FOR_CI`
- `CI_REMEDIATION`
- `WAITING_FOR_REVIEW`
- `REVIEW_REMEDIATION`
- `MERGE_READY`
- `WAITING_FOR_HUMAN`
- `CAPACITY_DEGRADED`
- `CAPACITY_BLOCKED`
- `IDLE_NO_READY_WORK`
- `FAULT_IDLE_WITH_READY_WORK`
- `INCIDENT`

`IDLE_NO_READY_WORK` is healthy. `FAULT_IDLE_WITH_READY_WORK` is not.

## Work selection

The scheduler should prefer work that is:

1. dependency-ready;
2. clearly bounded;
3. risk-reducing or value-delivering;
4. testable with available infrastructure;
5. achievable inside current budget/capacity;
6. unlikely to conflict with another active WU.

Avoid giant WUs that require weeks of context and cannot be independently merged.

## Role model

Roles are temporary responsibilities. Common roles:

- Orchestrator
- Product/Architecture Planner
- Implementer
- Repository Intelligence Scout
- Regression Scout
- Test Designer
- Failure Analyst
- Security Reviewer
- Independent Code Reviewer
- CI Remediator
- Merge Executor
- State Reconciler
- Documentation Maintainer

An actor may hold different roles on different WUs. What matters is eligibility and conflict-of-interest rules.

## Handoffs

A good handoff contains:

```text
WU ID
objective and non-goals
canonical branch/PR
exact current head
what has already been verified
current CI/review state
remaining blocker
constraints/budget
authorship and gate conflicts
what artifact proves completion
```

Never make a failover worker reconstruct the task from hundreds of chat messages.

## Remediation discipline

When a gate fails:

1. classify failure precisely;
2. inspect the failing tool/log;
3. use the repository-pinned tool to reproduce it;
4. change the smallest thing that addresses the cause;
5. preserve WU scope;
6. push to the same branch;
7. invalidate stale review verdicts;
8. rerun required verification.

Repeated speculative edits are a signal to switch to an executor with the right environment/capability.

## Completion

A WU is not done when “the code looks right.” It is done when:

- acceptance criteria are met;
- exact-head required CI is green;
- required independent review is satisfied;
- configured findings are resolved/accepted;
- merge is complete;
- linked issue/state is reconciled;
- lease is released;
- follow-up work is captured, not silently forgotten.
