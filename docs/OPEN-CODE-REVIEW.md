# OpenCodeReview in OneCompany

OneCompany uses Alibaba OpenCodeReview (OCR) as an **advisory review scaffold**, not as a governance authority.

## Why it fits OneCompany

OCR adds deterministic file selection, per-path review rules, precise diff positioning, incremental review support, and structured findings around an LLM reviewer. That complements OneCompany's own deterministic trust and assurance gates: OCR can improve defect discovery without becoming part of the root of trust.

The project profile is committed at:

```text
.opencodereview/rule.json
```

It focuses reviews on OneCompany's highest-risk invariants: platform-derived identity, trusted-base governance, exact head/base evidence, reviewer independence, lease liveness/expiry, transitive dependency admission, cache non-authority, policy truthfulness, workflow supply-chain safety, and the zero-additional-spend boundary.

## Governance boundary

OCR is **never** an eligible replacement for the independent human Code Owner approval required by protected `main`.

The upstream GitHub publisher submits PR reviews with event `COMMENT`, not `APPROVE`. Even if a future integration posts under a branded GitHub App identity, OneCompany must treat the result as advisory technical evidence only.

The protected-main ruleset remains authoritative:

- one approving review;
- Code Owner review;
- stale approvals dismissed after push;
- approval of the most recent reviewable push;
- all review conversations resolved;
- required `validate` check;
- no bypass actors.

## Recommended zero-additional-spend mode

Use **OCR delegation mode** with an already-paid coding-agent subscription such as Claude Code or Codex. OCR handles deterministic engineering and the host agent performs the reasoning with its existing subscription quota. OCR itself does not require an LLM endpoint in this mode.

Pin the CLI version used for a review. The initial OneCompany integration was evaluated against OCR `v1.12.1`.

```bash
npm install -g @alibaba-group/open-code-review@1.12.1
```

### Review a branch

```bash
ocr delegate preview --from main --to HEAD
```

Use the returned reviewable file list to resolve the matching OneCompany rules:

```bash
ocr delegate rule <path1> <path2> ...
```

For each reviewable file, the host agent should inspect the exact diff and any necessary surrounding context, then report only actionable findings with file/line, severity, violated invariant, exploit/failure path, remediation, and missing regression coverage.

### Full control-plane audit

For a release or trust-boundary change, use OCR's file-selection/rule machinery as the review plan and then perform a full agent audit of the selected trusted surfaces. Do not infer merge readiness from OCR output alone; merge readiness remains a OneCompany exact-head/base decision.

## Claude Code

When Claude Code is the reviewer, use OCR delegation mode so Claude consumes its existing subscription rather than a separate API key. The review must still state the exact target head and base and preserve material authorship/independence semantics.

OCR can also install a Claude command/skill upstream, but OneCompany does not vendor a floating upstream command. Any local installation should be pinned or reviewed before use.

## Codex

The same delegation flow can be used with Codex when quota is available. OCR improves deterministic file/rule coverage; Codex remains the reasoning engine. A Codex/OCR review is advisory unless the GitHub platform records a separately eligible approval from an independent human Code Owner.

## GitHub automation - intentionally not required

OCR ships a GitHub Actions integration that can post inline review comments. OneCompany does **not** make it a required check by default because:

1. automated OCR requires an LLM endpoint/token outside delegation mode;
2. this repository has a zero-additional-spend constraint;
3. private-repository GitHub Actions minutes are metered after the included allowance;
4. AI service availability or quota must never become a merge-authority dependency;
5. the upstream default uses `pull_request_target`, which OneCompany deliberately forbids for trusted workflows;
6. the stock publisher emits `COMMENT` reviews, not approvals.

If automated OCR is enabled later, the integration must:

- trigger from `pull_request`, never `pull_request_target`;
- avoid executing untrusted candidate code with secrets;
- pin every external GitHub Action to an immutable commit SHA;
- pin the OCR CLI/release version and preferably verify the release digest;
- use least-privilege `contents: read` and `pull-requests: write` permissions;
- bind review output to the exact PR head SHA;
- remain advisory and non-required unless a later governance change proves deterministic availability and evidence semantics;
- stop rather than incur paid overage or activate a paid fallback.

## Human reviewer continuity

Protected CompanyOS paths have two human Code Owners: `@NTinkicht` and `@kaporal159`. The author/last pusher cannot satisfy their own final approval, so the other human supplies the independent platform approval. OCR, Claude, Codex, Copilot, or any other automated reviewer can strengthen the technical review but cannot replace that human gate.
