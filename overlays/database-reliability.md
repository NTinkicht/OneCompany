# Overlay: Database Reliability

## Lens

Challenge persistence changes for concurrency, atomicity, migration safety, recoverability, and deterministic behavior.

## Ask

- What concurrent interleavings can violate invariants?
- Which rows/resources must be locked or version-checked?
- Are retries idempotent and exact?
- Can migration ordering or partial deployment break old/new code?
- Is rollback/recovery behavior tested?
- Are constraints doing useful work at the database boundary?

## Expected artifact

A concurrency/failure matrix, migration risk assessment, and deterministic regression tests or concrete findings.
