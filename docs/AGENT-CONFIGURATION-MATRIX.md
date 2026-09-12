# Agent Configuration Matrix

Use this as the fast audit before enabling an actor. The detailed steps are under `docs/agent-setup/`.

| Actor | Primary setup surface | Auth/cost distinction | Read smoke | Write smoke | Review smoke | Unattended default |
|---|---|---|---|---|---|---|
| ChatGPT | ChatGPT GitHub app/plugin | ChatGPT plan != OpenAI API billing | read policy/file + live repo state | only on separately authorized write surface | exact-SHA non-author artifact | no generic wake required |
| Codex | native Codex repo/workspace; optional repo-scoped PAT fallback | implementation/review quota may differ | `git/gh` repo preflight | disposable branch/PR | non-authored exact head | surface-dependent |
| Claude | Claude Code; optional Claude GitHub Action | subscription/OAuth != Anthropic API metering | policy + repo inspection | disposable WU branch | exact-SHA non-author gate | disabled template |
| GitHub Copilot | IDE/CLI, cloud agent, code review | feature/credit/Actions entitlement varies | repo/instruction awareness | cloud-agent disposable WU | Code Review on non-authored head | automations off until reviewed |
| Gemini CLI | local CLI; optional guarded Action | Google OAuth/free allowance != API/Vertex billing | read-only impact map | explicit leased branch only | non-authored exact head if configured | disabled read-only template |
| Mistral Vibe | local CLI; optional guarded Action | plan/free/PAYG can share key path | read-only failure/test task | explicit leased branch only | non-authored exact head if configured | disabled read-only template |
| Custom/local | project-defined | classify before use | required | capability-specific | capability-specific | shadow/read-only first |

## Definition of `configured`

`configured=true` means the intended execution surface can authenticate and reach the target repository. It does **not** mean every declared capability is available.

## Definition of `verified capability`

A capability belongs in `.onecompany/readiness.json -> verified_capabilities` only when that exact path has durable smoke evidence.

Examples:

- `implementation`: worker can make/test/push a bounded branch change.
- `ci_remediation`: worker can reproduce the repository CI toolchain and push a fix.
- `code_review`: worker can inspect the exact head and publish a durable review artifact.
- `merge_execution`: worker can mechanically merge with expected-head protection under policy.
- `repository_intelligence`: worker can inspect repository-wide evidence without unintended mutation.

## Capability degradation

Temporary quota/runtime failure belongs in `temporarily_unavailable_capabilities`. Do not disable the whole actor unless the whole execution surface is unusable.

## Minimum viable company

You do not need six models. Before L2/L3, ensure you have:

```text
1 implementation route
+ deterministic CI
+ 1 independent review route (AI or human)
+ an orchestrator/reconciliation path
+ a stop/revoke mechanism
```

Everything else improves resilience and specialization rather than defining basic correctness.
