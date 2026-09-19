# OneCompany Design Foundations

OneCompany is a reusable CompanyOS, not the operating diary of a particular
customer application. Its design draws on coordination failure modes, formal
software-engineering practices and independently attributed external research.

## Reusable operational constraints

- A canonical implementation lease and branch/PR per bounded Work Unit.
- Independent parallel work only when declared scopes and resources permit it.
- Deterministic tests and non-author assurance bound to exact head and base.
- Material authorship survives failover, retries, replay and cherry-picks.
- Capacity and budget are hard eligibility checks, not fallback suggestions.
- Live repository and durable ledger outrank chat and local state caches.
- Worker routing does not imply a verified executable dispatch path.
- Emergency stop, recovery and human-only decisions remain explicit.

## Organizational adaptation

Temporary delivery cells, reusable engineering standards and optional
specialist overlays provide aligned autonomy. These labels never confer
credentials, capacity, merge authority or reviewer independence. Relevant
external engineering-culture material is acknowledged in
`docs/REFERENCES.md`.

## Experimental infrastructure

Run optional agents, routers, reviewers and context compression alongside
the existing authoritative path in shadow mode. Preserve original evidence,
measure misses and high-impact failures, and require explicit reviewed
graduation with rollback before granting any new decision authority.

## Product boundary

Project names, infrastructure identifiers, schema history, approvals, active
Work Units and release procedures are installation-owned records. OneCompany
ships portable schemas, adapters, policies, templates and synthetic tests.
Bootstrap starts with empty per-target state and observe-only authority.
