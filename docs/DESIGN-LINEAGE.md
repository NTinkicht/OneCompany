# OneCompany Design Lineage

OneCompany combines general distributed-systems coordination, software
engineering assurance and bounded agent automation. Its source history records
how these mechanisms evolved without making any application its reference
implementation or a required deployment target.

## Technical sources

- Aligned autonomy: temporary delivery cells, shared discipline standards and
  optional cross-cutting specialties. See
  [pattern](../patterns/spotify-aligned-autonomy.md) and
  [references](REFERENCES.md).
- Actor/capability separation: a worker has identity, permissions and verified
  capacity; a role overlay is only a professional lens. See
  [role overlays](../patterns/role-overlays.md).
- Reproducible agent infrastructure: pin behavior-bearing upstream versions,
  preserve attribution and test in shadow mode before extending authority.
- Durable coordination: one canonical Work Unit/branch/PR, exclusive writer
  lease, deterministic evidence, independent exact-head/base review, idempotent
  external effects and replay-safe state reconciliation.
- Bounded autonomy: risk, budget, permissions and human-only decisions are
  hard constraints, not routing preferences.

## General engineering invariants

1. Assigned work is not progress; verified artifacts are progress.
2. Failover changes the worker, not the branch, PR or accumulated authorship.
3. A moved head or base invalidates dependent assurance.
4. An actor declaration does not prove ready executable capacity.
5. Quota exhaustion is not permission to buy capacity.
6. A cached repository snapshot is not live deployment authority.
7. Shadow adoption cannot create a second active mutation writer.
8. A code merge is not a release or schema-migration authorization.
9. Human sovereignty and emergency stop survive every autonomy level.
10. Neither the core nor fresh installations inherit any client's actual
    environment IDs, branch rules, credentials, approvals, backlog or data.

Every adopting project supplies its own requirements, stack, security,
runtime ownership, worker roster and independently reviewed release policy.

See [product boundary](PRODUCT-BOUNDARY.md),
[patterns](../patterns/README.md), and [references](REFERENCES.md).
