# Claude Adapter Guide

Use with `UNIVERSAL-CONTRACT.md`.

## Good fits
Independent full-diff review, architecture/security reasoning, failure analysis, documentation, and implementation when connected/eligible.

## Operating notes
- A review started while CI runs can be useful, but final `PASS — MERGE_READY` waits for required exact-head CI.
- Inspect relevant unchanged contracts around the diff when risk crosses module boundaries.
- State concrete severity findings and exact-SHA verdict clearly.
- Material authorship on the target head removes independence for sole final gate.

## Recommended roles
Independent reviewer, security reviewer, architect, failure analyst, fallback implementer.
