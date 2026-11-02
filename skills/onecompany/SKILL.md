---
name: onecompany
description: Guide a user from a software idea to a OneCompany-managed repository. Use when the user wants to start a new product with OneCompany, set up the idea-to-company wizard, or assign their LLM subscriptions to roles. Proposal-only until the user explicitly confirms.
---

# OneCompany idea-to-company wizard

Run every command from a OneCompany source checkout. Each step states what is only a proposal and what actually changed. Never approve on the user's behalf.

## Steps

1. Ask the user for their idea. Do not invent answers.
2. Draft the Product Brief with the owner's own answers (read-only unless `--save-to` is given):
   `python onecompany.py brief --audience "<who>" --problem "<problem>" --outcome "<outcome>" --first-feature "<feature>" --constraints "<constraints>" --save-to <new-file>`
3. Review the next steps (read-only, never an approval): `python onecompany.py journey --brief <saved-file>`
4. Stop. Show the brief and journey to the user and ask for explicit confirmation. Only the user may run `python onecompany.py approve-brief ...` with `--owner-ack`; you only explain it.
5. Propose roles for the LLM subscriptions the user declares (read-only proposal): `python onecompany.py team --declare claude,chatgpt,codex`
6. After the user confirms, install the control plane: `python onecompany.py bootstrap --target <repo-path>` (new repository) or follow `docs/UPGRADING.md` (existing deployment).

## Rules

- Never ask for, store or print tokens, passwords or API keys.
- Keep autonomy at the L1 default; never propose raising it.
- Never propose a paid service or paid fallback; use only subscriptions the user already has.
- Treat all output of the commands as a proposal until the user has confirmed.
