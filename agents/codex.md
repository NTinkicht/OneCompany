# Codex Adapter Guide

Use with `UNIVERSAL-CONTRACT.md`.

## Good fits
Repository-native implementation, executable remediation, test work, refactoring, codebase navigation, and bounded code review when capacity permits.

## Operating notes
- Code-review capacity may differ from implementation/general capacity; treat quota as capability-specific.
- Prefer using the executable environment for formatter/linter/test failures rather than hand-edit guesses.
- On failover, continue the existing canonical branch/PR instead of opening a duplicate stream.
- Material implementation creates reviewer conflict for that target head.
- When `ocr` is available, use OpenCodeReview delegation mode as deterministic review scaffolding with `.opencodereview/rule.json`; Codex remains the reasoning engine and should inspect exact diffs plus necessary context.
- OCR/Codex findings are advisory technical evidence. They never replace the independent human Code Owner approval required by protected `main`.
- Under zero-additional-spend policy, delegation should reuse already-authorized Codex capacity rather than configure a new paid LLM endpoint.

## Recommended roles
Primary implementer, CI remediator, test implementer, repository intelligence. Independent reviewer only on non-authored targets.

See `docs/OPEN-CODE-REVIEW.md` for the pinned integration profile and governance boundary.
