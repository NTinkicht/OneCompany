# Pattern: Spotify-Inspired Aligned Autonomy

## Problem

A multi-agent company needs both autonomy and alignment. Centralizing every decision in one orchestrator wastes capacity; giving every worker unconstrained autonomy creates conflicting branches, duplicated work, and inconsistent standards.

## Source and adaptation

Spotify's published engineering-culture material described autonomous squads connected by chapters and guilds. Spotify explicitly presented that material as a journey/snapshot rather than a prescriptive framework. OneCompany adopts only the useful organizational ideas.

OneCompany therefore uses the principles, not a literal copy of Spotify's org chart.

## OneCompany mapping

### Squads → bounded delivery cells

A squad is temporary and exists around one Work Unit / issue / canonical branch / PR. It has explicit responsibilities for orchestration, implementation, verification/review, and merge execution. It dissolves when the WU is done.

### Chapters → reusable discipline standards

Chapters are standards, not meetings or queues. Examples: architecture, implementation/CI, security/privacy, QA/review, UX/accessibility/localization, reliability.

Chapter knowledge should become contracts, tests, schemas, checklists, or role overlays.

### Guilds → advisory cross-cutting overlays

Guilds are optional specialist lenses spanning delivery cells: security, migrations/concurrency, localization, context efficiency, developer productivity, research/scouting. They do not create binding authority by themselves.

### What OneCompany intentionally does not copy

- permanent provider-to-role assignment;
- mandatory ceremonies;
- hierarchy for its own sake;
- a second work queue for chapters/guilds;
- the assumption that organizational labels create autonomy.

## Core principle: aligned autonomy

Workers should be free to execute inside a bounded contract while company-wide invariants constrain safety, cost, review independence, and merge authority.

Autonomy without alignment drifts. Alignment without autonomy bottlenecks.

## When to use

Use this pattern when more than one actor can contribute concurrently or when specialist standards must survive worker/provider changes.

For a single human + single agent, keep the vocabulary light but preserve the separation between delivery work and reusable standards.

## Failure modes

- **Cargo-cult structure:** creating squads/chapters/guilds without concrete responsibilities.
- **Permanent squads:** binding a provider to a job forever instead of routing by live capability.
- **Guild authority creep:** advisory specialists silently becoming merge gates.
- **Ceremony inflation:** standups/meetings consuming more effort than artifacts.

## OneCompany invariant

The vocabulary may change; bounded autonomous delivery plus shared executable standards must remain.
