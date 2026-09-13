# Architecture

OneCompany is a **control plane**, not a single AI agent. It coordinates heterogeneous workers around GitHub and enforces contracts that survive provider/model changes.

## Layers

```text
┌────────────────────────────────────────────────────────────┐
│ Human governance                                           │
│ budget, autonomy, credentials, irreversible decisions     │
├────────────────────────────────────────────────────────────┤
│ Company policy                                             │
│ constitution, roles, security, review/merge contracts     │
├────────────────────────────────────────────────────────────┤
│ Orchestration                                              │
│ observe → reconcile → select → route → lease → continue    │
├────────────────────────────────────────────────────────────┤
│ Worker plane                                               │
│ ChatGPT / Codex / Claude / Copilot / Gemini / Mistral /…  │
├────────────────────────────────────────────────────────────┤
│ Verification plane                                         │
│ formatting, lint, types, tests, build, audit, review       │
├────────────────────────────────────────────────────────────┤
│ GitHub source of truth                                      │
│ issues, branches, PRs, SHAs, Actions, comments, merges     │
└────────────────────────────────────────────────────────────┘
```

## Control-plane documents

`.onecompany/config.json` — project-level configuration and autonomy policy.

`.onecompany/actors.json` — current worker roster, capability scores/preferences, permissions, and cost/capacity classes.

`.onecompany/roles.json` — reusable role contracts. Roles are responsibilities, not identities.

`.onecompany/budget.json` — explicit financial and capacity policy.

`.onecompany/queue.json` — planned Work Units/dependencies. Live issues/PRs remain source of truth once work begins.

`.onecompany/state.json` — reconciled snapshot for fast coordination. It must never overrule live GitHub reality.

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
  ↓ exact-head pass
MERGE_READY
  ├─ head moved → CI_PENDING/REVIEW_PENDING
  ↓ expected-head merge
MERGED
  ↓
RECONCILED / DONE
```

## Why one canonical stream

Parallel exploration is useful; parallel implementation of the same bounded objective is usually wasteful and dangerous. OneCompany permits analysis by many actors but grants one write lease for the canonical branch/PR. This avoids:

- conflicting fixes;
- duplicated token/subscription capacity;
- ambiguous authorship;
- review races;
- stale gates;
- “which branch is real?” failures.

Experimental forks are allowed only when the Work Unit explicitly authorizes a comparative experiment.

## Router architecture

Routing is a constrained decision, not a popularity contest.

Input:

```text
required capabilities
risk class
write/read requirement
context size
latency preference
current capacity/quota
budget policy
authorship conflicts
provider availability
```

Output:

```text
eligible actor + reason + fallback chain
```

Hard constraints are evaluated before preferences. For example, a model may be the best reviewer but ineligible because it materially authored the head.

## Lease architecture

A lease is a concurrency primitive. A minimal implementation lease contains:

```json
{
  "work_unit": "WU29",
  "role": "implementation",
  "actor": "codex",
  "branch": "wu29-example",
  "pr": 174,
  "start_head": "abc123",
  "scope_hash": "optional",
  "status": "active",
  "granted_at": "ISO-8601",
  "expires_or_failover_when": ["quota_exhausted", "no_progress", "human_override"]
}
```

Leases should be reconciled against actual branch/PR state before being trusted.

## Review architecture

Review contains two classes:

- **deterministic gate:** CI commands with reproducible pass/fail;
- **independent judgment gate:** code/security/product reasoning anchored to exact SHA.

The default final verdict vocabulary is deliberately small:

```text
PASS — MERGE_READY
CHANGES_REQUIRED
BLOCKED — CI_RED
BLOCKED — HUMAN_DECISION
BLOCKED — CAPACITY
```

Projects may extend it but should keep machine-readable equivalents.

## State reconciliation

Never assume `.onecompany/state.json` is current just because it is committed. A reconciler should compare at least:

- current open WU issues;
- open PRs and exact heads;
- merge/closed state;
- active CI runs and conclusions;
- recorded lease owner vs branch activity;
- current review verdict SHA;
- unresolved configured-severity findings;
- budget/capacity state when observable.

Reconciliation should be idempotent.

## Communication architecture

GitHub owns durable coordination. Optional Slack/Discord/Teams/email layers are for attention and culture:

```text
GitHub = authoritative state
Slack = “look here”
Chat = interactive reasoning
Local tools = execution environment
```

Never require reconstructing project truth from chat history.

## Deployment models

### Minimal
Human + one implementer AI + one independent reviewer AI + GitHub Actions.

### Subscription-only
Several interactive/GitHub-native workers using already-paid subscriptions; no API billing.

### Local-first
Local models/tools perform repository intelligence/tests; stronger remote models handle high-value reasoning.

### Enterprise
Organization-owned runners, secrets, policy enforcement, audit storage, mandatory human gates for defined risk classes.

OneCompany is intentionally neutral across all four.
