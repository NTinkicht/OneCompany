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

## Live read-only Mistral qualification (2026-09-20 UTC / 2026-09-21 Asia/Dubai)

**Verified, narrow scope only:** GitHub-hosted owner-authorized read-only
`@mistral-vibe` wake on #130 executed authentic model inference on protected
`main@9834c646eaa6ffb16b5471583ec4a554e14a5331` in
[run 35540501655](https://github.com/NTinkicht/OneCompany/actions/runs/35540501655);
the [github-actions[bot] result](https://github.com/NTinkicht/OneCompany/issues/130#issuecomment-5753004827)
correctly identified the commit, no-extra-spend budget, wake ≠ lease, and
a relevant deterministic test idea. This followed the negative preflight
runs 35539354626 (`CONFIG_BLOCKED`) and 35539634038 (`AUTH_BLOCKED HTTP 401`).
The owner corrected the private Vibe key and the zero-spend variable before
the positive run. `vibe-readonly-wake` alone is configured and the
`repository_intelligence` and `test_design` capabilities have live evidence;
this does **not** verify a lease-bound developer, a binding independent
reviewer, a model-authored test commit, a PR merge, or Grok Bot unattended
execution. Do not send the key to an issue or another actor.

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

**Repeatable positive smoke (originally completed as run 35540501655):**
owner posts `@mistral-vibe Read AGENTS.md and identify the actor's read-only
permissions in 3 sentences; do not mutate files.` on issue #130. Check the
`OneCompany Mistral Vibe Wake` run and its `github-actions[bot]` issue reply.
Positive evidence: model-generated correct bounded output, run link, correct
source repository, no secret, correct issue, Codespace/laptop off. Negative
evidence: untrusted issue/author/comment skips, missing key/PAYG var reports
`AUTH_BLOCKED`/`CONFIG_BLOCKED` without inference or paid fallback.

**Readiness policy:** the positive run establishes only read-only repository
intelligence and test design. The wake mechanism is now configured=true while
code-writing, binding review and merge mechanisms remain configured=false. Do not infer eligibility from source code or
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
**Preferred: officially documented Grok Bot**, not a private Codespace or an
exported browser session. [Provider overview](https://docs.x.ai/grok-bot/overview)
says Bot runs on a persistent provider cloud computer that keeps working when
your laptop and app close. [Owner onboarding](https://docs.x.ai/grok-bot/get-started)
requires a Cursor account linked to the eligible individual SuperGrok plan;
[Skills/routines](https://docs.x.ai/grok-bot/skills-routines-and-automations)
describes event-triggered routines from GitHub notifications where available.
[FAQ](https://docs.x.ai/grok-bot/faq) states weekly included usage and
**optional separately metered on-demand usage**.

Owner must verify Grok Bot access, link existing SuperGrok, disable any optional
on-demand/auto-topup or enforce zero additional spend, and review its required
cloud-data-storage privacy mode. The Bot's connector/plugins are not
automatically identical to the existing Grok chat's OneCompany MCP. Configure
only a single OneCompany read-only GitHub scope initially. Prove a narrow
GitHub notification event wakes that Grok Bot and publishes a durable result
while all owner machines are off. Neither availability of the UI nor a routine
created in Grok proves delivery to GitHub without a live response.

Alternative experiment: official Grok Build CLI subscription auth on ephemeral
GitHub Actions. Official docs cover headless scripting and cached auth, but do
**not** prove a secure, renewable SuperGrok session on a brand-new ephemeral
runner without owner reauthentication. Do **not** transfer
`~/.grok/auth.json` or refresh tokens into Actions for a speculative smoke;
do not create `XAI_API_KEY`, use metered xAI API, install a third-party
GitHub Action holding the subscription session, or grant App write permissions.
If neither existing-plan cloud path can be qualified, mark unattended Grok
capacity `CAPACITY_BLOCKED` with a specific provider limitation, and use
other eligible workers rather than demand a Codespace. Never classify an
owner-OAuth GitHub write as bot-authored Grok code.

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
