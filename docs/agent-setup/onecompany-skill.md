# OneCompany setup for Codex, Gemini CLI and Copilot

Give your agent these plain instructions (copy into its own instruction mechanism; this repository's `AGENTS.md`, `CLAUDE.md` and `GEMINI.md` are not edited by this page).

Run from a OneCompany source checkout, one step at a time, and wait for the user between steps:

1. Ask the user for their idea and the Product Brief answers. Do not invent answers.
2. `python onecompany.py brief --audience ... --problem ... --outcome ... --first-feature ... --constraints ... --save-to <new-file>`
3. `python onecompany.py journey --brief <saved-file>` (read-only; never an approval).
4. Stop and ask the user to confirm. Only the user runs `approve-brief` with `--owner-ack`.
5. `python onecompany.py team --declare <comma-separated actors>` (read-only proposal).
6. After confirmation: `python onecompany.py bootstrap --target <repo-path>`.

Rules: never ask for tokens or secrets; keep autonomy at L1; never propose paid services; say clearly what is a proposal and what changed.
