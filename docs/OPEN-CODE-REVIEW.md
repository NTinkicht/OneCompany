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

OCR is an advisory review scaffold; it does not replace deterministic CI,
independent non-author technical review or OneCompany's exact-head/base merge
gate. The former platform approval policy and two-person CODEOWNERS roster
are historical and no longer describe this repository.

Routine technical PRs need no manually requested reviewer. Source ownership
is assigned only to the repository owner. Exceptional budget, credentials,
constitutional, legal and destructive-production decisions follow the separate
governance policy.

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

The same delegation flow can be used with Codex when quota is available. OCR improves deterministic file/rule coverage; Codex remains the reasoning engine. A Codex/OCR review contributes independent technical evidence only when reviewer independence and the exact head/base are verified by OneCompany.

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

## Review continuity

CodeRabbit, Codex and other eligible non-author technical reviewers may
supply advisory findings for the current exact SHA. Evidence and required
checks remain separate. Do not request another individual on routine PRs.
