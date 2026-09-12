# Agent Onboarding

Every worker should receive the universal contract plus a provider-specific adapter guide.

## Universal onboarding sequence

Before acting, an agent should read:

1. `company/CONSTITUTION.md`
2. `.onecompany/config.json`
3. `.onecompany/budget.json`
4. `.onecompany/actors.json`
5. `.onecompany/roles.json`
6. `.onecompany/state.json` **as cache only**
7. current WU/issue and live PR/CI state

Then it should answer internally:

- What role am I holding right now?
- Am I permitted to write?
- What is the canonical branch/PR/head?
- What exact artifact proves my task is complete?
- Am I a material author and therefore conflicted from final review?
- Does budget policy permit the execution path I intend to use?
- What human-only boundary could I cross accidentally?

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
Budget/security constraints
Expected completion artifact
```

Provider-specific guides in `agents/` explain practical strengths/limitations but do not override the universal contract.
