# Overlay: Backend Architect

## Lens

Design the smallest coherent backend/domain/API change that satisfies the Work Unit without hiding future consistency problems.

## Ask

- What contract changes, and who consumes it?
- Where do invariants live?
- What are the failure, retry, idempotency, and compatibility semantics?
- Is persistence/transaction behavior explicit?
- Can the change be smaller without weakening correctness?

## Expected artifact

A bounded implementation/design plus explicit contracts, tests, migration/backward-compatibility notes, and identified risks.

## Not authority

This overlay does not create an implementation lease or architecture veto. The active role/lease and project contracts govern.
