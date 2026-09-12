# Agent Setup - From Account to Verified Worker

An AI subscription/account is **not** the same thing as a routable OneCompany actor.

OneCompany uses four separate layers:

1. **Declared capability** - `.onecompany/actors.json` says what this actor type can potentially do.
2. **Connection/configuration** - the product/CLI/app is installed and authenticated for this repository.
3. **Verified readiness** - `.onecompany/readiness.json` records what has actually been smoke-tested: surfaces, capabilities, and repository access.
4. **Current availability** - temporary quota/runtime problems are recorded per capability without disabling unrelated capabilities.

Never store credentials in `.onecompany/readiness.json`. Store only non-secret evidence such as `read smoke passed in setup issue #12` or `write smoke PR #13`.

## Recommended setup order

1. Configure GitHub itself (`docs/GITHUB-SETUP.md`).
2. Decide budget/cost classes (`docs/BUDGET-CAPACITY.md`).
3. Configure one implementer.
4. Configure a genuinely independent reviewer.
5. Configure the orchestrator/state-reconciliation path.
6. Add QA/scouting/reserve actors.
7. Only then consider unattended wake paths.
8. Run `python onecompany.py readiness --local-probe`, `validate`, `simulate`, and the first-run acceptance plan.

## Provider guides

- [ChatGPT](chatgpt.md)
- [Codex](codex.md)
- [Claude / Claude Code](claude.md)
- [GitHub Copilot](copilot.md)
- [Gemini CLI](gemini-cli.md)
- [Mistral Vibe](mistral-vibe.md)
- [Custom/local agent](custom-agent.md)

## Readiness rule

Do not set an actor to `enabled: true` merely because you own a subscription. Enable it only after the intended execution path has been configured and the capabilities you intend to route have evidence in `.onecompany/readiness.json`.

A typical lifecycle is:

```text
not_started -> partially_ready -> ready
                         \-> degraded -> ready
                         \-> unavailable
```

Example: Codex implementation works but review quota is exhausted. Keep the actor ready/degraded, preserve `implementation` in verified capabilities, and add `code_review` to `temporarily_unavailable_capabilities`. The router can continue using Codex for implementation without incorrectly assigning it a review.
