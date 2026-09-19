# OneCompany product boundary

OneCompany is a reusable, domain-independent company operating system. Its
repository contains generic policies, planning and execution engines, adapters,
schemas, templates, documentation and synthetic regression fixtures. It does
**not** act as the repository of record for any customer's or product's
runtime/deployment/migration state.

## Three distinct ownership scopes

1. **OneCompany product:** implementation, reusable governance, generic
   bootstrap defaults, synthetic demonstration scenarios, and tests.
2. **Adopting project:** its repository and contract, owners, task backlog,
   branches/PRs, runtime accounts, credentials, environment IDs, writer
   inventory, audit evidence, releases and recovery.
3. **Optional external orchestration service:** target metadata only through
   explicitly configured per-tenant boundaries, authenticated permissions
   and independent evidence stores. Never bake client identities or live
   access into a distributed core, CLI, pattern library or starter template.

A real project may provide a sanitized regression scenario for a generic bug,
but not its actual repository identifiers, deploy IDs, personal identities,
migration approvals, credentials or live security posture. Git history
preserves prior reviewed work, without importing it into future installations.

## Architecture contract

- New projects are initialized from inputs provided at installation time;
  no customer or demonstration project is a prerequisite.
- An existing project is onboarded by a read-only inspection and a separate
  governed installation decision. No application-specific assumptions are
  carried from earlier onboardings.
- Every target supplies its own requirements, stack/tests/CI, budget, human
  approvers, hosting, credentials, recovery and autonomy policy.
- Routing, leasing, assurance, exact-head gates, emergency stop and spend
  constraints remain reusable across all projects.
- Operator/runbook evidence must stay in the corresponding target or an
  explicitly target-owned evidence store, not in the OneCompany product repo.
- L1 or a green PR cannot silently grant OneCompany a target mutation
  capability or increase autonomy.

## Release hygiene

The core CI checks for source-level target-specific evidence and tests that
two synthetic targets can exercise the same onboarding/shadow APIs while
remaining isolated. Any new example should use placeholder identities and
be unambiguously labelled synthetic; third-party source attribution is
different from a live target integration.
