# Team wizard

`python onecompany.py team --declare claude,chatgpt,codex,copilot,gemini,mistral,grok [--json] [--save-to NEW_FILE]`

Proposes which declared LLM should take each role in `.onecompany/roles.json`, using `routing.json` `preference_by_capability` restricted to what you declare. It is a read-only proposal: it makes no network or provider call, never edits `actors.json`, `readiness.json` or `routing.json`, and grants no authority.

Rules:

- Names may be actor ids or the short aliases `copilot`, `gemini`, `mistral`, `grok`. Empty, unknown and duplicate names are refused; `human-owner` is always available and is not declared.
- Only the `INCLUDED_SUBSCRIPTION` cost class is considered. Other declared actors are listed as excluded with their cost class. `.onecompany/budget.json` must allow no additional spend or the wizard refuses.
- The implementer and CI remediator are never the independent reviewer or security reviewer.
- With fewer than two distinct eligible actors, independent review, security review and merge fall back to `human-owner`, with a warning.
- Every assignment is `UNQUALIFIED`: owning a subscription never makes an actor ready (`docs/FIRST-RUN-ACCEPTANCE.md`). Each row names the next step, `python onecompany.py qualify-worker --json` and the matching `docs/agent-setup/` page.
- `--save-to` writes a proposal file only: new file, mode 0600, never overwritten.
