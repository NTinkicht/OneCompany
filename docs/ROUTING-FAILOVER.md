# Capability Routing and Failover

## Principle

Route **capabilities**, not brands. A worker identity is an implementation detail of the company roster.

## Routing pipeline

### 1. Determine required role/capabilities
Example implementation WU:

```text
required: implementation, TypeScript, tests
preferred: repository_intelligence, failure_analysis
write_access: required
independent_gate_conflict: irrelevant for implementer
```

### 2. Apply hard eligibility filters
Reject actors that:

- lack required permission/environment;
- are forbidden by budget policy;
- are unavailable/quota-exhausted;
- cannot access required repository context;
- are materially conflicted for the target review role;
- would violate data/security policy.

### 3. Rank eligible actors
Possible preference signals:

- capability fit;
- current capacity/headroom;
- included/free vs metered cost;
- latency;
- context size;
- recent task success;
- environment/tool access;
- task specialization.

### 4. Produce fallback chain
Record an ordered list of *eligible* alternatives. Do not list a paid actor when paid fallback is forbidden.

## Example roster strategy

A subscription-only project might prefer:

```text
implementation: Codex → ChatGPT → GitHub Copilot → other eligible writer
independent review: Claude → CodeRabbit/Copilot review → another non-author reviewer
repository intelligence: Gemini CLI → local tooling → any read-capable actor
test/failure analysis: Mistral Vibe → Claude → ChatGPT
```

This is only an example. OneCompany does not require these brands or this order.

## Failover triggers

Recommended triggers:

- explicit quota/capacity exhaustion;
- actor unavailable/outage;
- missing environment required to reproduce failure;
- no durable progress before lease timeout/heartbeat threshold;
- repeated same failed remediation pattern;
- permission failure;
- human override;
- security concern.

## Failover procedure

1. Reconcile current branch/PR/head.
2. Stop/release prior write lease.
3. Preserve current canonical branch and PR.
4. Record authorship accumulated so far.
5. Grant replacement actor a lease from the exact current head.
6. Hand off objective, acceptance contract, current blocker, logs, and prior attempts.
7. Replacement actor must inspect current reality before editing.
8. Continue existing CI/review lifecycle.

Do **not** open another branch merely because the worker changed.

## Authorship after failover

Material authorship is cumulative. If ChatGPT wrote product logic and Copilot later only formatted a test, ChatGPT remains a material author. Final independent gate eligibility must consider all material authors of the candidate head, not just the latest committer username.

## Capacity states

- `AVAILABLE`
- `DEGRADED`
- `QUOTA_LIMITED`
- `UNAVAILABLE`
- `FORBIDDEN_BY_BUDGET`
- `FORBIDDEN_BY_POLICY`
- `UNKNOWN`

Unknown should normally be treated conservatively for unattended spending/actions.

## Zero-spend behavior

If every eligible writer is temporarily unavailable and paid fallback is forbidden:

```text
CAPACITY_BLOCKED
```

is correct behavior. Silently spending money is not.
