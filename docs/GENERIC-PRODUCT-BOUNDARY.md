# Generic product boundary

OneCompany is a reusable **project factory and orchestration product**, not
the release ledger or control plane of a specific customer project. A fresh
installation may operate any project **only after** that project independently
supplies its contracts, evidence, authority and verified execution surface.

| OneCompany product | Individual project or isolated authorized tenant state |
| --- | --- |
| engine, schemas, CLI, generic worker adapters | domain, requirements and backlog |
| invariant governance checks, templates, synthetic fixtures | actual owners, PRs, CI and branch protection |
| provider-agnostic capability contracts | concrete service/database accounts, secrets and migrations |
| generic cutover/release procedures | per-project go/no-go, recovery drill and deployment history |

Never check target-specific `source-evidence/`, `evidence/`, provider IDs,
deployment records, named-project examples or application runbooks into the
product repository. The bootstrap creates fresh queue/state/identity and
requires target-specific setup; it cannot import a source project's writers,
licenses, approval decisions or secrets. An operator's authority in one
installation cannot grant privileges in another.

Historical issues and commits remain an audit trail, **not live defaults**.
Active project records migrate to the owning project before removal from
the product tree. Reusable fixes to the generic engine flow upstream through
ordinary independently reviewed OneCompany PRs.

## General creation flow

1. Create or connect any repository.
2. Bootstrap with that repository's name, principals and contracts.
3. Collect fresh, scoped read-only facts and verified provider capacities.
4. Prove exact-head CI, independent review, budget and rollback.
5. Advance autonomy only under an explicit owner-approved policy and drills.
6. Keep running target data and release evidence with its owner.

A future multi-project supervisor may use a separate tenant registry, but
customer IDs and their capability leases belong **outside product source**.
