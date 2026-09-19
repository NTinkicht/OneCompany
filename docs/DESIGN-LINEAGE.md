# Design Lineage and Generic Invariants

OneCompany is a reusable orchestration and software-company operating
product. Its design draws on multi-agent delivery experience and published
engineering practices. This source tree contains **general rules**, not
operating records or privilege assignments for any customer project.

## Aligned autonomy

Spotify's engineering-culture material described squads, chapters and guilds.
OneCompany adapts useful principles, not a literal organization chart:

- Work Unit + canonical branch/PR + leases: bounded delivery ownership;
- engineering contracts and deterministic tests: reusable discipline;
- optional specialist overlays: advisory expertise independent of identity.

## Specialist profiles

The MIT-licensed upstream `msitarzewski/agency-agents` library helped frame
generic professional lenses. An overlay is **not** a worker, permission,
subscription, reviewer identity, lease or merge authority.

## Context and shadow adoption

Research on context compression informed a deterministic-first context ladder.
Optional compressors, routers, reviewers and agents begin in read-only shadow
mode; original evidence remains authoritative, omission risks are measured,
and promotion requires review rather than an automatic policy change.

## Core coordination invariants

1. One canonical implementation stream and explicit lease per bounded WU.
2. Parallel lanes only for non-conflicting work with verified capacity.
3. Deterministic CI and independent non-author review at the **same head**.
4. Budget/quota exhaustion is a visible capacity blocker, not spend consent.
5. Derived state must reconcile with the actual source-of-truth platform.
6. Failover changes an eligible worker, not the branch, PR or authorship.
7. Consequential authority and autonomy increases remain explicitly governed.
8. Project evidence, deployment ownership, credentials and domain contracts
   are installation-specific; they never ship as product defaults.

## Provenance versus authority

External public references and licenses belong in `docs/REFERENCES.md`.
Per-project engineering evidence belongs to its source project or separate
authorized state store. Historical Git commits remain an audit trail but
cannot be used as current target authority or product defaults.
