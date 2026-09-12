# Codex Adapter Guide

Use with `UNIVERSAL-CONTRACT.md`.

## Good fits
Repository-native implementation, executable remediation, test work, refactoring, codebase navigation, and bounded code review when capacity permits.

## Operating notes
- Code-review capacity may differ from implementation/general capacity; treat quota as capability-specific.
- Prefer using the executable environment for formatter/linter/test failures rather than hand-edit guesses.
- On failover, continue the existing canonical branch/PR instead of opening a duplicate stream.
- Material implementation creates reviewer conflict for that target head.

## Recommended roles
Primary implementer, CI remediator, test implementer, repository intelligence. Independent reviewer only on non-authored targets.
