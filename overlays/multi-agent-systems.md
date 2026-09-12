# Overlay: Multi-Agent Systems

## Lens

Review the company control plane itself: authority, routing, leases, authorship, failover, context, trust boundaries, and progress evidence.

## Ask

- Is there exactly one canonical implementation stream?
- Can two workers believe they own the same write lease?
- Does failover preserve history and authorship?
- Can an author become its own independent gate indirectly?
- Does routing check cost/availability/permission as well as capability?
- Is derived state reconciled against live source-of-truth evidence?
- Can untrusted content alter governance or tool permissions?
- Are no-idle rules producing useful work rather than busywork?

## Expected artifact

A control-plane risk map with concrete invariants, failure cases, and simulation/test recommendations.
