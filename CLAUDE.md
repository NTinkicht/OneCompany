# Claude in OneCompany

Read `AGENTS.md`, `agents/UNIVERSAL-CONTRACT.md`, and `agents/claude.md` before acting.

Claude is often a strong independent reviewer, security reviewer, architect, or failure analyst, but roles are assigned dynamically. If Claude materially authors the candidate head, preserve that authorship and use another eligible independent final reviewer.

A final review must name the exact target SHA and may emit `PASS — MERGE_READY` only when required exact-head CI is green and configured-severity findings are resolved.

## OpenCodeReview delegation

When `ocr` is available, prefer Alibaba OpenCodeReview delegation mode as deterministic review scaffolding for branch or commit reviews. The project-specific rules live in `.opencodereview/rule.json`; see `docs/OPEN-CODE-REVIEW.md`.

OCR may determine reviewable files and resolve per-path rules, but Claude remains responsible for the reasoning, context exploration, severity judgment, and falsification attempts. OCR output is advisory evidence only and never satisfies the independent human Code Owner approval required by protected `main`.

Do not configure a paid OCR LLM endpoint or paid fallback merely to obtain a review. Under the zero-additional-spend policy, use delegation mode with the already-authorized Claude subscription unless an explicit governance decision approves another route.
