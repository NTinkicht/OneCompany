# Claude in OneCompany

Read `AGENTS.md`, `agents/UNIVERSAL-CONTRACT.md`, and `agents/claude.md` before acting.

Claude is often a strong independent reviewer, security reviewer, architect, or failure analyst, but roles are assigned dynamically. If Claude materially authors the candidate head, preserve that authorship and use another eligible independent final reviewer.

A final review must name the exact target SHA and may emit `PASS — MERGE_READY` only when required exact-head CI is green and configured-severity findings are resolved.
