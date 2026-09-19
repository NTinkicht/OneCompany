# Product-neutrality boundary

OneCompany is a reusable multi-project operating system, not automation tied
to a particular customer application.

Its distributable code includes generic orchestration, planning, policy,
capability routing, leases, review gates, worker adapters, installers and
synthetic regression fixtures. It must not ship client names, staging or
production infrastructure IDs, real deployment runbooks, application schema
evidence, incident logs, active Work Units, or target-specific approvals.

Each onboarded target owns its operating records in its own repository or a
separately scoped tenant evidence store. Onboarding discovers the target's
architecture, CI, workers, infrastructure and permissions; it cannot reuse a
different target's approval, credentials, merge/release authority or readiness.

The generic source must not contain root `source-evidence/` or `evidence/`
with named-project observations. Historical audit material remains in Git
history and, when applicable, is transferred to the owning project.

These boundaries are independent of autonomy level. A reusable generic
product must still require verified policy and explicit authority before it
operates any chosen project.
