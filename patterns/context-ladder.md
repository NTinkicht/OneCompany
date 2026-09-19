# Pattern: Deterministic-First Context Ladder

## Problem

Strong models waste time, context window, and subscription capacity when asked to rediscover repository structure, read giant logs, or repeatedly reconstruct state from chat history.

## Ladder

Use the cheapest, most deterministic source that can answer the question:

```text
cache/index
  -> git/search/diff/structured metadata
  -> bounded source/log slices
  -> verified local compression when suitable
  -> explicitly allowed bounded model compression
  -> strong reasoning actor
```

## Rules

1. Deterministic retrieval comes before semantic summarization when it can answer the question.
2. Pass only the bounded evidence needed for the task.
3. Compression is convenience, not authority.
4. Exact-head review, security/auth decisions, destructive migrations, concurrency proofs, leases, and owner decisions must be grounded in original evidence.
5. Secrets, production records, private dumps, and prohibited sensitive paths never enter optional compression stages.
6. If a summary seems surprising, expand the original evidence rather than arguing from the summary.

## Why this matters

Context is a budget. OneCompany treats token/context consumption like compute: route discovery to deterministic tools and reserve strong models for decisions that need reasoning.

## Operational consequence

Optional compression stays disabled until provenance, budget, privacy and loss-of-facts behavior are qualified. A cheaper model is not automatically safer.
