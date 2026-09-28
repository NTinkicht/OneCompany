# Cross-repository Mistral external review

OneCompany can provide bounded, review-only Mistral failover for approved public
sibling repositories when their native reviewer lane is unavailable.

Owner dispatch is posted to OneCompany Issue #130:

```text
@mistral-vibe
MISTRAL_EXTERNAL_REVIEW_V1
repo: NTinkicht/veritas-atlas
pr: 21
head_sha: <exact current PR head>
base_sha: <exact current PR base>
material_authors: chatgpt
```

The workflow verifies the owner dispatch and exact public target, checks material
author independence, checks out the target without credentials, builds a bounded
complete merge-base-to-head diff (with the current base SHA retained as provenance), rejects sensitive paths and secret-like evidence,
enforces zero-additional-spend Mistral preflight, and gives the model no tools.

The workflow publishes a github-actions[bot] result on Issue #130 and seals the
exact stored comment identity and digests in a run-scoped artifact. The workflow
can finish green only for a validated PASS. It has no target-repository write,
approval, or merge authority.

A target L4 controller must independently re-check the exact head/base, its own
CI, unresolved findings, author independence, and merge policy before accepting
the PASS evidence.
