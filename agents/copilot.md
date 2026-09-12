# GitHub Copilot Adapter Guide

Use with `UNIVERSAL-CONTRACT.md`.

## Good fits
GitHub-native implementation, IDE assistance, bounded remediation, test generation, and supplemental review.

## Operating notes
- Confirm the GitHub agent/IDE has the actual executable environment needed for the task.
- For mechanical failures, run the canonical repository tool and commit its output rather than approximating it manually.
- Do not open a new PR when taking over a failover lease for an existing WU.
- Track material authorship separately from GitHub committer identity.

## Recommended roles
Implementer, CI remediator, test implementer, supplemental reviewer on non-authored targets.
