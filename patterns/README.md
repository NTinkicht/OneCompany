# OneCompany Pattern Library

OneCompany is deliberately more than a bundle of prompts. Its reliability comes from a small set of organizational and distributed-systems patterns that can be adopted independently.

The machine-readable catalog is `.onecompany/patterns.json`. This directory explains the patterns, their provenance, trade-offs, and failure modes.

## Pattern map

| Pattern | Default | Problem it solves |
|---|---|---|
| `spotify-aligned-autonomy` | Core | Autonomy without losing shared standards/alignment |
| `single-stream-lease` | Core | Duplicate agents implementing the same bounded work |
| `orthogonal-parallelism` | Core | Using spare capacity without branch/PR collisions |
| `exact-head-two-key-gate` | Core | Self-review, stale reviews, model-confidence merges |
| `capacity-circuit-breaker` | Core | Quota exhaustion silently becoming paid usage |
| `context-ladder` | Recommended | Wasting strong-model context on repository discovery |
| `shadow-before-authority` | Recommended | Giving experimental infrastructure decision authority too early |
| `role-overlays` | Recommended | Generic agents missing domain/specialist lenses |
| `evidence-over-activity` | Core | Agents appearing busy without shipping durable work |
| `upstream-pinning` | Recommended | External tools/prompts changing behavior without review |

## Composition rules

Patterns are not independent in every combination:

- `single-stream-lease` + `orthogonal-parallelism` is the preferred concurrency model.
- `exact-head-two-key-gate` assumes material authorship is tracked across failovers.
- `capacity-circuit-breaker` must be consulted before actor routing.
- `context-ladder` and `shadow-before-authority` preserve original evidence as authority.
- `role-overlays` never create an actor, lease, permission, reviewer independence, or merge authority.
- `evidence-over-activity` is what makes no-idle safe: it prevents activity theater from satisfying the company loop.

## Do not cargo-cult the vocabulary

OneCompany uses patterns to address recurring coordination failure modes. Each installation preserves the invariant and may rename the mechanism. For example, a team does not need to call a temporary delivery group a “squad”; it needs bounded ownership, alignment, and a single canonical stream.

See `docs/DESIGN-LINEAGE.md` for provenance and `docs/REFERENCES.md` for source material.
