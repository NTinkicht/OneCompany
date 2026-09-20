# OneCompany cloud AI engineering team — Step 2 qualification

Status: **in progress, capability-specific**. This document is a qualification plan, not an
assertion that all four lanes are ready. The source repo remains L1 until separately
approved and qualified authority changes.

## Non-negotiable runtime requirement

No OneCompany worker's unattended eligibility may depend on Nassim keeping a
Codespace, workstation, browser, terminal, or Grok/Mistral chat open. Events must
be consumed by a genuine GitHub-hosted or provider-hosted runner. A PR comment
without a consumer is **not** execution. No new paid AI API, PAYG, overages,
persistent billable VM, or provider account/session-token export is allowed by
the USD 0 extra-spend source budget. A blocked actor does not block unrelated
qualified team members; authority for a *single canonical WU/PR* may be
transferred only through the native verified lease lifecycle.

## Mistral Vibe (source repo only)

The baseline copied/adapted from
[`Tabibi/.github/workflows/mistral-vibe-wake.yml`](https://github.com/NTinkicht/Tabibi/blob/main/.github/workflows/mistral-vibe-wake.yml)
is `.github/workflows/onecompany-mistral-vibe-wake.yml`. This is a
**GitHub-hosted, read-only, non-gating** issue-comment wake, guarded by:
- permanent OneCompany wake issue [#130](https://github.com/NTinkicht/OneCompany/issues/130);
- issue comment authored by `NTinkicht` containing `@mistral-vibe`;
- machine budget with zero additional monthly AI spend and no paid fallback;
- repository variable `ONECOMPANY_MISTRAL_PAYG_DISABLED_CONFIRMED=true`;
- GitHub Actions secret `MISTRAL_API_KEY` carrying a Vibe-eligible **included-plan**
  key, not a regular metered API key;
- non-inference Vibe entitlement `whoami` HTTP-status preflight;
- pinned `mistral-vibe==2.25.3`, Python 3.12 and pinned GitHub Actions;
- read/grep-only Vibe plan agent, bounded turns/tokens/time, redacted output;
- classified failures, no upgrade to write, binding review, or merge.

**Owner-only onboarding:** inspect Mistral console Subscription/usage and ensure
PAYG/overage is OFF for the *same account and key* to be used in OneCompany.
Under OneCompany Settings → Secrets and variables → Actions, add
`MISTRAL_API_KEY` privately and set
`ONECOMPANY_MISTRAL_PAYG_DISABLED_CONFIRMED=true` only after verification.
The connected GitHub tool cannot read or transfer Tabibi's stored secret.
Never paste the key, billing/session files, auth.json or PEM into issues/chats.
A Vibe `whoami` success is an entitlement probe, **not** evidence that PAYG is
disabled; verify billing in the provider console separately.

**Initial real smoke (after the reviewed workflow is on main):**
owner posts `@mistral-vibe Read AGENTS.md and identify the actor's read-only
permissions in 3 sentences; do not mutate files.` on issue #130. Check the
`OneCompany Mistral Vibe Wake` run and its `github-actions[bot]` issue reply.
Positive evidence: model-generated correct bounded output, run link, correct
source repository, no secret, correct issue, Codespace/laptop off. Negative
evidence: untrusted issue/author/comment skips, missing key/PAYG var reports
`AUTH_BLOCKED`/`CONFIG_BLOCKED` without inference or paid fallback.

**Readiness policy:** until the positive run, `mistral-vibe` remains disabled,
configured=false and verified_capabilities empty; the wake dispatch mechanism
remains configured=false. Do not infer eligibility from source code or
Tabibi's run history. After a successful independent verification, a separate
reviewed registry update may qualify *read-only* analysis/test-design; it must
not turn on implementation or binding review by association.

Separate role lanes, presently **not qualified**:
- [#133](https://github.com/NTinkicht/OneCompany/issues/133): leased developer.
  Native durable implementation lease and exact WU/PR/base/head/write-scope
  verified **in the trusted Action parent** before inference and again before
  publication; no model-held GitHub write token; parent-run CI; fast-forward
  expected-head push; bot or explicit `github-actions[bot]` + logical-actor
  attribution, no force, no self-review/merge.
- [#134](https://github.com/NTinkicht/OneCompany/issues/134): read-only
  independent reviewer with frozen base/head SHAs, cumulative authors, live CI
  evidence and a distinct trusted publication identity. If Mistral materially
  authored the candidate, it cannot be its own sole independent gate.
- [#135](https://github.com/NTinkicht/OneCompany/issues/135): QA analysis of
  trusted/redacted CI evidence, acceptance criteria and exact head; writing test
  files requires a valid implementation lease on the existing canonical PR.

## Grok / SuperGrok (no Codespace route)

The existing OneCompany GitHub App OAuth + read-only MCP is **GitHub I/O only**;
it does not provide an unattended Grok model process. The Tabibi Codespace
subscriber is explicitly **not an acceptable deployment architecture**.

Cloud inference qualification is [#131](https://github.com/NTinkicht/OneCompany/issues/131).
Research official Grok Build subscription support on ephemeral GitHub Actions
and provider-hosted Grok Automations as two independent experiments. Official
Grok Build docs describe cached account credentials and headless flows but
do **not** prove an unattended, self-renewing SuperGrok session on ephemeral
runners under this owner's billing/privacy restrictions. Do **not** transfer
`~/.grok/auth.json` or refresh tokens into Actions for a speculative smoke;
do not create `XAI_API_KEY`, use metered xAI API, install a third-party
GitHub Action holding the subscription session, or grant App write permissions.
Grok Automations must demonstrate a real GitHub-event consumer; do not invent
a native GitHub trigger. If neither secure existing-plan cloud path works,
mark unattended Grok capacity `CAPACITY_BLOCKED` with the precise provider
limitation, and use other eligible workers rather than demanding a live
Codespace. Never classify an owner-OAuth GitHub write as bot-authored Grok code.

The later [#136](https://github.com/NTinkicht/OneCompany/issues/136)
qualifies developer, independent exact-head reviewer and tester **only after**
the same no-Codespace inference smoke is real and attributed. The frozen
[#105](https://github.com/NTinkicht/OneCompany/issues/105) internal writer
requires a separate reviewed platform-lease smoke before owner-approved
scoped permission change.

## Acceptance — the full engineering team

Each enabled capability must have real GitHub run/PR/lease/SHA evidence:
1. event-driven model wake with all owner devices/Codespaces off;
2. bounded developer contribution on exactly one canonical WU/PR after valid lease;
3. independent non-material-author review against current head and base;
4. deterministic test execution and evidence publication tied to the exact head;
5. stale/revoked/duplicate-writer and unavailable-provider drills;
6. fail-closed zero-extra-spend and explicit authentication/identity provenance.

No evidence means `NOT_CONFIGURED`/`CAPACITY_BLOCKED`, not a marketing
readiness badge. Mistral and Grok qualifications do not themselves raise
OneCompany's source autonomy level.
