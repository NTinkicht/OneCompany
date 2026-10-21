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

## Owner-approved narrowly scoped TheraBridge review (issue #326)

The existing cross-repository reviewer remains restricted to **Tabibi** and **veritas-atlas** by default. A special **single-PR, single-head** exception has been proposed for the public `NTinkicht/TheraBridge-Emergent` PR #53. This is **not** blanket permission for TheraBridge, the private `NTinkicht/TheraBridge` specifications repository, or other public PRs.

Pinned target (changing any field rejects the dispatch):
- PR: `NTinkicht/TheraBridge-Emergent#53`, source head `cd5f721d9e4d68f756baa4109628c44f217c706a`
- Feature base ref `freebuff-tb-em-011-governance`, base SHA `b275f1b0e201d622bce1336a67d2d74f511fb2d4`
- GitHub-attested connector commits (in order) `b25453d17b002ca0d8c90ba21f3dd8a478750868`, `cd5f721d9e4d68f756baa4109628c44f217c706a`, both under the owner's `NTinkicht` GitHub account. The owner explicitly attests that ChatGPT materially authored this code. These specific historic commits have no Material-Author trailer; only **these exact SHA objects** can use this exception.
- Material author to exclude from independence: `chatgpt`. Mistral accounts, email identities, coauthors and commits are prohibited.
- The reviewer returns **advisory evidence on OneCompany Issue #130 only**. A review of `.github/workflows/ci.yml` is **never an automatic GitHub approval**, auto-merge, or clinical signoff. Target PR #53 and integration PR #54 stay draft.

After the OneCompany control-plane change is **independently reviewed, authorized and merged** to `main`, the authorized owner may post **once** to [OneCompany Issue #130](https://github.com/NTinkicht/OneCompany/issues/130) using the following literal dispatch:

```text
@mistral-vibe
MISTRAL_EXTERNAL_REVIEW_V1
repo: NTinkicht/TheraBridge-Emergent
pr: 53
head_sha: cd5f721d9e4d68f756baa4109628c44f217c706a
base_sha: b275f1b0e201d622bce1336a67d2d74f511fb2d4
material_authors: chatgpt
```

The `issue_comment` workflow on `main` checks that the issue author is `NTinkicht`, then verifies live target SHA/base, public visibility, provenance, emergency stop, budgets, no paid fallbacks, full bounded diff and output proof. A blocked capacity/credential status is **not** a successful review. This is a **manual, one-shot dispatch**, not an addition to auto-dispatch `TARGETS`.

Review policy: inspect service scoping, concurrent access revocation, guardian-message read gates, exact-head CI integrity and cross-specialty tests. Do not expose private canonical specifications or real child/patient records. A validated Mistral verdict remains advisory. If it flags issues, use a separately reviewed code fix and recompute exact head before retry.
