# Dispatch and Wake: Routing Is Not Execution

A company can select the perfect worker and still stall if it has no executable way to start that worker.

OneCompany therefore separates:

```text
routing.json    -> who should do this?
readiness.json  -> can that capability actually work now?
dispatch.json   -> how can this worker actually be started on this repository?
```

## Why this matters for 24/7 operation

A scheduled supervisor that decides “Codex should fix CI” has not completed the handoff until a configured executable mechanism exists. A comment that no runtime consumes is only a marker.

Use:

```bash
python onecompany.py dispatch --actor codex --capability ci_remediation --unattended
```

If no verified unattended path exists, OneCompany returns `CAPACITY_BLOCKED`. The supervisor must use another eligible actor/path or surface a genuine blocker. It must not invent a provider API key or paid route.

## Example mechanisms

Possible surfaces include:

- active ChatGPT conversation with GitHub tools;
- ChatGPT scheduled/event-triggered Work task;
- Codex GitHub/native assignment, automation, workspace or CLI;
- persistent Claude/Claude Code session;
- reviewed Claude Code GitHub Action;
- Copilot coding-agent assignment or Code Review request;
- Gemini CLI local execution;
- guarded read-only Gemini GitHub Action;
- Mistral Vibe local execution;
- guarded read-only Vibe GitHub Action;
- explicit human action.

The reference registry ships every provider mechanism `configured=false`. A target project records only the mechanisms it has actually configured and tested.

## Dispatch does not create authority

A mechanism is transportation, not permission. It cannot override:

- the active role/lease;
- repository permissions;
- budget policy;
- material-authorship/reviewer independence;
- exact-head gate requirements;
- human-only decisions.

Generic unattended scout wakes should not be reused as implementation or binding-review paths unless a separate reviewed mechanism explicitly grants and proves that authority.

## Handoff completeness

A valid unattended handoff needs both:

1. a routed eligible actor for the capability; and
2. a configured, verified dispatch mechanism that can actually consume the task.

Without both, the company is not continuously operable for that capability.
