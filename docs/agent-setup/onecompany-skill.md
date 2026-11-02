# OneCompany setup for Codex, Gemini CLI and Copilot

Give your agent these plain instructions (copy into its own instruction mechanism; this repository's `AGENTS.md`, `CLAUDE.md` and `GEMINI.md` are not edited by this page).

Run from a OneCompany source checkout, one step at a time, and wait for the user between steps:

1. Ask the user for their idea, the target repository path (`<target>`) and its `OWNER/REPO` (`<repository>`), plus the Product Brief answers. Do not invent answers. Pass the same `--target <target> --repository <repository>` to every command below that accepts them.
2. `python onecompany.py brief --target <target> --repository <repository> --audience ... --problem ... --outcome ... --first-feature ... --constraints ... --save-to <new-file>`
3. `python onecompany.py journey --target <target> --repository <repository> --brief <saved-file>` (read-only; never an approval).
4. Stop and ask the user to confirm the brief conversationally. This is not a work-unit approval.
5. `python onecompany.py team --declare <comma-separated actors>` (read-only proposal).
6. After confirmation: `python onecompany.py bootstrap --target <target> --repository <repository>`. Work-unit admission needs the installed target queue.
7. Only after installation may the user run `approve-brief` with `--owner-ack`; you only explain it.

Rules: never ask for tokens or secrets; keep autonomy at L1; never propose paid services; say clearly what is a proposal and what changed.
