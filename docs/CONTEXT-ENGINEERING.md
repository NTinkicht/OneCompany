# Context Engineering

OneCompany treats context as infrastructure and budget, not as an invitation to paste the whole repository into every model turn.

## Deterministic-first ladder

```text
known cache/index
 -> git/search/diff/structured GitHub metadata
 -> bounded source/log slices
 -> optional verified local compression in shadow mode
 -> optional explicitly budgeted model compression
 -> strong reasoning actor
```

## Startup context

Every material worker should receive/read:

- `AGENTS.md` / universal contract;
- current Work Unit;
- live PR/head/CI/review state;
- current lease/material authors;
- budget/readiness state relevant to its route;
- only task-relevant architecture/security/product contracts and selected overlays.

Avoid routinely injecting all history and all docs.

## Evidence hierarchy

Summaries/compression are indexes. Expand original evidence for:

- exact-head binding review;
- security/auth/authorization decisions;
- destructive migrations;
- concurrency/data-integrity proofs;
- credentials/permissions;
- owner decisions;
- surprising or ambiguous claims.

## Sensitive exclusions

Do not feed secrets, private keys, production database dumps, regulated/customer records, provider payloads, or credential-bearing logs into optional context compressors/models merely to save tokens.

## Optional compression

A project may add Headroom or another local/context tool, but start with `patterns/shadow-before-authority.md`:

1. pin provenance/version;
2. use historical/non-sensitive samples;
3. compare original-context and compressed-context decisions;
4. record compression/latency/fact-preservation/omission metrics;
5. keep original retrieval reversible;
6. graduate only after project-specific fidelity evidence.

A good average compression ratio does not compensate for a blocker/security fact being omitted.

## Hooks/read guards

For large repositories, tool hooks may discourage accidental unbounded reads and point workers to deterministic discovery/bounded slices. Such hooks must not prevent complete original evidence retrieval when correctness requires it, and should not invoke paid models invisibly.
