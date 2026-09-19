# Capability Routing and Failover

## Principle

Route **capabilities**, not brands. Provider tendencies are preferences; live readiness, budget, permissions, authorship, and policy are hard filters.

Machine policy:

```text
.onecompany/actors.json      potential capability
.onecompany/readiness.json   proven capability/access/current degradation
.onecompany/routing.json     capability-specific preference order
.onecompany/budget.json      financial eligibility
.onecompany/state.json       current authorship/leases/gate cache
```

## Routing pipeline

### 1. Determine required capability

Examples: `implementation`, `code_review`, `repository_intelligence`, `test_design`, `failure_analysis`, `merge_execution`.

### 2. Apply hard eligibility filters

Reject actors that:

- are disabled/unconfigured;
- do not declare the capability;
- have not verified the capability on the intended surface;
- are temporarily unavailable for that capability;
- lack required read/write/review/merge access;
- are forbidden by budget policy;
- are materially conflicted for independent review;
- would violate data/security policy.

### 3. Apply capability-specific preference

Only after hard filters, rank using `.onecompany/routing.json`. The following optional, illustrative preferences are not binding assignments:

```text
planning/orchestration      ChatGPT first
implementation             Codex first
independent code review    Claude first
repository intelligence    Gemini CLI first
failure analysis           Mistral Vibe first
test design / QA           GitHub Copilot first
merge execution            Codex first
```

These are replaceable preferences, not job ownership. The optional human owner is a fallback/safety route when its corresponding capabilities are explicitly verified.

Use:

```bash
python onecompany.py route --capability implementation
python onecompany.py route --capability code_review --for-independent-gate
```

The independent-gate route automatically excludes `state.current_material_authors`; `--exclude-author` can add additional conservative exclusions.

The first eligible result is a **proposal, not a lease**.

## Capability-specific degradation

Do not disable an actor globally because one quota/surface fails. Example:

```text
Codex implementation: verified + available
Codex code_review: temporarily unavailable
```

The router may still propose Codex for implementation and reject it for review.

## Failover triggers

Recommended triggers:

- explicit quota/capacity exhaustion;
- actor/runtime unavailable;
- missing environment required to reproduce failure;
- no durable progress **after live evidence is reconciled**;
- repeated same failed remediation pattern;
- permission failure;
- human override;
- security concern.

A timer/heartbeat alone is not sufficient evidence to wake a competing implementer.

## Same-stream failover procedure

1. Reconcile current branch/PR/head.
2. Diagnose which capability is unavailable.
3. Route an eligible replacement.
4. Transfer the existing implementation lease atomically while preserving WU/branch/PR/history.
5. Preserve cumulative material authorship.
6. Hand off objective, acceptance contract, current blocker, CI/findings, prior attempts, budget/security constraints.
7. Replacement inspects current reality before editing.
8. Continue the existing CI/review lifecycle.

Executable helper:

```bash
python onecompany.py lease transfer \
  --actor <replacement-actor> \
  --current-head <exact-current-sha> \
  --reason quota_exhausted
```

Do **not** open another branch merely because the worker changed.

## Non-preemption rule

If a replacement is healthy and actively making progress on the canonical stream, recovery of the preferred actor does not automatically preempt it mid-attempt. Finish or perform an explicit safe handoff.

## Authorship after failover

Material authorship is cumulative and stored conservatively in `state.current_material_authors`. Failover/cherry-pick/replay does not launder authorship. Final independent gate routing automatically excludes tracked authors.

## Capacity states

Useful operational states include:

- `ready`
- `degraded`
- `unavailable`
- capability-specific temporary unavailability
- forbidden by budget/policy
- unknown

Unknown should normally fail closed for unattended spending/actions.

## Zero-spend behavior

If every eligible writer is temporarily unavailable and paid fallback is forbidden, a visible capacity blocker is correct behavior. Silently spending money is not.
