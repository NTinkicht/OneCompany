# Work Units

A Work Unit (WU) is OneCompany’s atomic delivery contract. It should be small enough that one implementation stream can finish, verify, independently review, and merge it without requiring speculative parallel work.

## Required fields

### Identity
- WU ID (`WU01`, `WU29`, etc.)
- title
- parent objective/epic
- priority
- risk class

### Problem
State the observable problem or capability gap. Avoid solution-only descriptions.

### Objective
One sentence describing the post-merge behavior.

### Scope
Explicit in-scope files/components/behaviors where known.

### Non-goals
Write what this WU must **not** grow into.

### Dependencies
Other WUs, migrations, decisions, credentials, infrastructure, or external constraints.

### Acceptance criteria
Behavioral outcomes that can be verified.

### Verification contract
Required deterministic checks plus special tests.

### Security/privacy constraints
Sensitive data boundaries, authorization behavior, logging restrictions, fail-open/fail-closed decisions.

### Budget/capacity constraints
For example: no new paid service, no metered API, existing subscriptions only.

### Human decisions
Anything the company cannot decide autonomously.

### Routing
Capabilities required for implementation and final review.

## Good size

A good WU usually has:

- one coherent behavioral objective;
- one canonical branch/PR;
- acceptance criteria that fit on one screen;
- tests that can run independently;
- low ambiguity about done/not-done.

Split work when there are multiple independently valuable behaviors, unrelated risk surfaces, or incompatible reviewers.

## Dependency-ready definition

A WU is `READY` only when:

- every hard dependency is satisfied;
- required human decisions are complete;
- required credentials/infrastructure exist;
- current budget permits at least one eligible implementation route;
- no active WU owns a conflicting write scope unless explicitly coordinated.

## WU lifecycle

```text
PROPOSED → READY → LEASED → IN_PROGRESS → CI_PENDING
                                         ↘ remediation
CI_GREEN → REVIEW_PENDING → MERGE_READY → MERGED → DONE
                ↘ remediation
```

A WU may transition to `BLOCKED` from most states, but the blocker must be explicit and actionable.

## Acceptance anti-patterns

Bad:
- “works well”
- “improve performance”
- “make it secure”
- “Claude likes it”

Better:
- “unauthorized delivery invokes the provider zero times”
- “p95 query latency under the benchmark fixture is < X ms”
- “CI command `npm test` passes on the candidate SHA”
- “no secret/contact payload values appear in persisted observability events”

## Follow-ups

Review findings outside WU scope should become explicit follow-up WUs/issues. Do not smuggle unrelated cleanup into the current branch unless needed to safely complete it.

## Work Unit template

Use `.github/ISSUE_TEMPLATE/work-unit.md` as the durable source. `.onecompany/queue.json` may summarize proposed/dependency state but should not duplicate every issue body.
