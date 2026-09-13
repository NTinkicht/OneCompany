# Agent Onboarding

Every worker receives the universal contract plus a provider-specific behavior adapter **and** a setup/readiness runbook.

Start with `docs/agent-setup/README.md`. Owning an account/subscription does not make an actor routable.

## Universal onboarding sequence

Before acting, an agent should read:

1. `AGENTS.md` / `agents/UNIVERSAL-CONTRACT.md`
2. `company/CONSTITUTION.md`
3. `.onecompany/config.json`
4. `.onecompany/budget.json`
5. `.onecompany/actors.json`
6. `.onecompany/readiness.json`
7. `.onecompany/roles.json`
8. `.onecompany/patterns.json` / selected overlay
9. `.onecompany/state.json` **as cache only**
10. current WU/issue and live PR/CI/review state

Then it should answer internally:

- What role am I holding right now?
- Which exact capability is verified for this execution surface?
- Am I permitted to read/write/review/merge?
- What is the canonical branch/PR/head?
- What exact artifact proves my task is complete?
- Am I a material author and therefore conflicted from final review?
- Does budget policy permit the execution path I intend to use?
- Is this capability temporarily degraded even if other capabilities still work?
- What human-only boundary could I cross accidentally?

## Setup before enablement

For each actor:

1. follow its guide under `docs/agent-setup/`;
2. install/connect/authenticate the intended surface;
3. grant least privilege;
4. smoke-test read access;
5. smoke-test write/review/merge separately only when intended;
6. record non-secret evidence/capabilities in `.onecompany/readiness.json`;
7. set actor `configured=true` and `enabled=true` only when the route is usable;
8. run `python onecompany.py validate` and `route` tests.

## Minimal handoff packet

```text
Role
WU ID/objective
Canonical branch/PR
Exact current head
Acceptance criteria
Current CI status
Current findings/blocker
Material authors
Actor capability/readiness constraint
Budget/security constraints
Expected completion artifact
```

## Provider guides

Behavior adapters live in `agents/`. Setup/authentication/runbooks live in `docs/agent-setup/`. Provider documentation may change, so verify current vendor instructions before activating a disabled automation template.
