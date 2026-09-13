# Architecture

OneCompany is a **company control plane**, not a single AI agent. It coordinates heterogeneous workers around GitHub and enforces contracts that survive provider/model changes.

## Layers

```text
┌────────────────────────────────────────────────────────────┐
│ Human sovereignty                                          │
│ mission boundaries, budget, credentials, legal/governance │
├────────────────────────────────────────────────────────────┤
│ Strategy / planning baseline                               │
│ objectives, epics, requirements, ACs, risks, WUs          │
├────────────────────────────────────────────────────────────┤
│ Company policy                                             │
│ constitution, roles, security, assurance, review/merge    │
├────────────────────────────────────────────────────────────┤
│ Flow control                                               │
│ observe → reconcile → plan → route → lease → supervise    │
├────────────────────────────────────────────────────────────┤
│ Worker plane                                               │
│ ChatGPT / Codex / Claude / Copilot / Gemini / Mistral /…  │
├────────────────────────────────────────────────────────────┤
│ Verification plane                                         │
│ formatting, lint, types, tests, assurance, review          │
├────────────────────────────────────────────────────────────┤
│ GitHub execution evidence                                  │
│ issues, branches, PRs, SHAs, Actions, reviews, merges      │
└────────────────────────────────────────────────────────────┘
```

## Split source-of-truth model

OneCompany distinguishes **approved intent** from **live execution evidence**.

### Approved planning baseline

Versioned control-plane files are authoritative for approved machine-executable intent:

- `.onecompany/portfolio.json` — Objectives, Epics, Features/Capabilities, optional User Stories, milestones/releases and their links;
- `.onecompany/requirements-catalog.json` — formal requirements and acceptance-criterion definitions;
- `.onecompany/risk-register.json` — planning risks and treatments;
- `.onecompany/queue.json` — bounded Work Units, dependencies, priority inputs, scope/locks, issue/PR mapping;
- `.onecompany/planning.json` — planning/parallelism policy.

GitHub Issues and Projects are the preferred collaboration and visualization surface. They may propose or discuss changes, but an edited issue does not silently re-baseline approved requirements, risk or scope.

### Live execution evidence

GitHub is authoritative for live reality:

- open/closed/merged PR state;
- exact head and base SHAs;
- branch content;
- changed files;
- Actions/check conclusions;
- reviews/comments;
- merge result.

`.onecompany/state.json` is a reconciled cache and never overrules live GitHub.

## Planning hierarchy

The model is flexible rather than Scrum-specific:

```text
Objective
  ↓
Epic
  ↓
Feature / Capability       optional
  ↓
User Story                 optional
  ↓
Formal Requirements
  ↓
Acceptance Criteria
  ↓
Work Units
  ↓
Tasks / Enablers / Spikes / Defects / Chores
  ↓
Tests / Evidence / Release / Outcome
```

A backend/infrastructure project can omit User Stories. A Task is not a Requirement, and an Epic is not merely a large Work Unit.

## Work Unit state machine

```text
PROPOSED
  ↓
READY ───────────────→ BLOCKED
  ↓                      │
LEASED                   │ dependency/capacity/human
  ↓                      │ resolution
IN_PROGRESS ←────────────┘
  ↓
CI_PENDING
  ├─ red → REMEDIATION → CI_PENDING
  ↓ green
REVIEW_PENDING
  ├─ findings → REMEDIATION → CI_PENDING
  ↓ exact-head + exact-base pass
MERGE_READY
  ├─ head moved → CI_PENDING/REVIEW_PENDING
  ├─ base moved → REBASE/UPDATE → CI_PENDING/REVIEW_PENDING
  ↓ expected-head/base merge
MERGED
  ↓
RECONCILED / DONE
```

## One canonical stream **per Work Unit**

OneCompany preserves single-writer authority inside a bounded WU:

- one canonical issue/contract;
- one canonical branch/PR;
- at most one active implementation lease;
- one current head;
- failover changes the worker, not the stream.

That invariant does **not** require the whole company to serialize.

## Conflict-safe company parallelism

Multiple WUs may run concurrently only when the planner can prove they are independent under configured policy.

Admission considers:

- hard dependency relationships;
- declared write scopes;
- semantic resource locks;
- risk class;
- global WIP limit;
- per-actor verified implementation capacity.

Unknown scope fails closed to serialization. Critical-risk work serializes by default. Live PR diffs are checked against declared scope before a merge-ready gate and again before merge.

Example:

```text
WU-A: src/auth/**       lock auth:policy
WU-B: web/marketing/**  no lock
WU-C: migrations/**     lock auth:policy + db:schema

WU-A + WU-B  → may run concurrently
WU-A + WU-C  → conflict; serialize
```

## Parallel merge train / base drift

Exact head identity alone is insufficient when branches are developed concurrently.

A merge-ready gate records both:

```text
candidate head SHA
candidate base SHA
```

If another WU merges and the base moves, the previous integration evidence becomes stale even when the candidate head is unchanged. The merge executor refuses the stale gate and requires update/rebase plus required CI/review again.

This preserves fast parallel implementation without allowing stale integration evidence onto `main`.

## Router architecture

Routing is a constrained decision, not a popularity contest.

Input includes required capability, risk, repository permission, current verified readiness, worker capacity, budget, material-authorship conflicts and provider availability. Hard constraints are evaluated before preferences.

A routing preference is never authority. A route is not a lease, and a lease is not evidence of progress.

## Lease architecture

A lease is a concurrency/authority primitive. A minimal implementation lease contains:

```json
{
  "work_unit": "WU29",
  "role": "implementation",
  "actor": "codex",
  "branch": "wu29-example",
  "pr": 174,
  "start_head": "abc123",
  "planning_snapshot": {
    "write_scope": ["src/module/**"],
    "resource_locks": ["module:api"],
    "risk_class": "MEDIUM"
  },
  "status": "active"
}
```

Durable claim races enforce one writer per WU, company WIP and actor capacity.

## Review architecture

Review contains two classes:

- **deterministic gate:** reproducible CI/assurance commands;
- **independent judgment gate:** non-author code/security/product reasoning.

Binding merge-ready evidence is anchored to exact head **and base**, verified scope, current material authors and durable evidence references.

## Reconciliation

Before consequential mutation, reconcile:

- versioned WU/PR mapping;
- live open PRs and exact heads/bases;
- merge/closed state;
- CI state;
- active leases and worker capacity;
- gate SHA/base/authorship;
- blockers/human decisions;
- budget/capacity state when observable.

Reconciliation is idempotent. Ambiguous authority fails closed.

## Communication architecture

```text
Versioned .onecompany graph = approved intent / planning baseline
GitHub Issues/Projects       = collaborative UI / discussion surface
GitHub PRs/Actions/reviews   = live execution evidence
Chat                         = interactive reasoning
Local tools                  = execution environment
```

Never require reconstruction of project truth from chat history.

## Deployment models

### Minimal
Human + one implementer AI + one independent reviewer AI + GitHub Actions.

### Subscription-only
Several workers using already-paid subscriptions/free allowances with zero additional API spend.

### Local-first
Local models/tools perform repository intelligence/tests; remote models handle high-value reasoning.

### Governed autonomous company
Multiple conflict-safe WUs, event-driven supervision, durable coordination, exact-head/base gates, outcome measurement and human sovereignty over restricted decisions.

OneCompany is intentionally provider-neutral across all modes.
