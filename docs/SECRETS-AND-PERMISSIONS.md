# Secrets and Permissions

OneCompany separates **capability**, **credential**, and **permission**. A model may be capable of merging while its credential is intentionally unable to merge.

## Secret stores

Use the narrowest platform-native store:

- local interactive CLI: OS credential store / provider login / protected environment;
- Codex cloud/workspace: that environment's secret store;
- GitHub Actions: repository/environment/organization Actions secrets;
- Copilot cloud agent external resources: GitHub **Secrets and variables → Agents**;
- CI cloud provider: its workload identity/OIDC where supported.

Never put secrets in `.onecompany/*.json`, instruction files, issues, PR comments, artifacts, example `.env` files, or shell command arguments that may be logged.

## Access classes

| Class | Typical need | Suggested repository authority |
|---|---|---|
| Scout/research | inspect source/issues/CI | read contents, issues/PRs/checks |
| Test/failure analyst | inspect + maybe test-only changes | read; write only if explicitly leased |
| Implementer | modify canonical WU stream | branch contents + PR/issue interaction |
| Independent reviewer | inspect exact head + publish review | read + review/comment; no implementation write required |
| Merge executor | merge approved exact head | PR merge only where possible; no admin/secrets |
| Orchestrator | reconcile/coordinate | read + issue/PR coordination; code write only under explicit failover lease |

## Provider credential matrix

The names below are examples/reference templates, not requirements to create every secret.

| Surface | Credential example | Default policy |
|---|---|---|
| ChatGPT GitHub app | OAuth/GitHub App authorization | repository read/context; write separately verified |
| Codex native | product-managed GitHub connection | preferred when sufficient |
| Codex PAT fallback | fine-grained repo PAT in Codex environment | optional, repo-scoped, minimum permission |
| Claude Action | `CLAUDE_CODE_OAUTH_TOKEN` when supported | subscription-backed path preferred for zero-extra-spend |
| Anthropic API | `ANTHROPIC_API_KEY` | metered; forbidden unless budget explicitly allows |
| Gemini local | Google OAuth | preferred for individual/free/included use when eligible |
| Gemini unattended | `GEMINI_API_KEY` | only with explicit billing guard/cost classification |
| Vertex AI | Google Cloud identity/API | not zero-extra-spend default |
| Mistral interactive | Mistral account/Vibe setup | verify plan/PAYG state |
| Mistral unattended | `MISTRAL_API_KEY` | only with explicit PAYG-disabled/budget guard |
| Copilot cloud agent | GitHub entitlement; optional Agents secrets | use Agents secret store for external resources |

## Permission expansion is human-only by default

An agent may diagnose “I need write access” but should not silently grant itself broader scope. Credential creation, repository-admin permission, billing enablement, secret changes, and production access are human-only unless governance explicitly delegates them.

## Rotation/revocation

Document how to revoke every write-capable credential. Incident containment should be able to disable autonomous writes without deleting project history. If a secret is suspected exposed: revoke/rotate first, then investigate logs/artifacts/history.

## Logging

Never echo credential values. Reduce provider failures to categorical diagnostics such as `AUTH_REJECTED`, `QUOTA_EXHAUSTED`, `ENTITLEMENT_MISSING`, or `RUNTIME_TIMEOUT`. Scrub bearer/API-key patterns before publishing model output from unattended jobs.
