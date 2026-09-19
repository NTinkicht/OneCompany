# Product independence and per-project isolation

OneCompany is a **generic software-company operating system**, not an
operating notebook for any one application. It can help originate a new
product, bootstrap its project, or onboard an existing repository. Domain
language, product names, providers and operational endpoints must be supplied
by **each instance**, not hard-coded into the distribution.

## Boundaries

| Reusable OneCompany product | Project-owned instance |
| --- | --- |
| Planning engine, backlog/WU/lease schemas, actor capability routing | Product mission, market/user research and domain requirements |
| Exact-head CI/review gates, human sovereignty, emergency stop | Actual repository/branch policies, reviewer identities and permissions |
| Generic templates, contract validation, integration adapters | Language/framework choice, architecture, data model and UI |
| Generic release/rollback protocol and safety guards | Deploy IDs, database project IDs, secret revisions and recovery drills |
| Generic testing/simulation fixtures and *sanitized* lessons | Staging/production observations, incident logs and acceptance evidence |

A project-specific adoption manifest, writer inventory, auth test, incident
report or deployment runbook is stored in that project's repository or an
explicitly named private project workspace. It must **not** be committed to
OneCompany's distributed core, reusable docs, pattern catalog, starter
templates, reference fixtures or shared learning. A sanitized reusable
*rule* may enter OneCompany after separate review, without retaining
identifiers or granting authority.

Previously committed project snapshots remain in immutable Git history for
audit; removing them from the current product tree neither erases that
history nor changes any installed project. Source evidence moved to its
own project's repository is authoritative only at its original observation
boundary; the transfer is not a refreshed current-state inspection.

## Creating any new project

1. Collect an idea and human mission. Define users, measurable outcomes,
   constraints, data sensitivity, budget and the human-only decisions.
2. Establish project contracts using generic templates. Choose stack,
   infrastructure and compliance requirements **from the product's needs**,
   not by inheriting a previous project's architecture.
3. Provision a distinct repository/project identity and infrastructure
   only with independently verified credentials, permissions and owner
   authorization. No paid overage or implicit secret sharing.
4. Bootstrap a **fresh** OneCompany instance: empty queue, portfolio,
   ledger bindings, active leases and derived state; disabled mutation
   authority and supervision by default.
5. Test stack-specific CI and controls; qualify each actual implementation
   worker/capacity path. Run read-only onboarding and shadow reconciliation.
6. After explicit scoped authority, execute bounded Work Units, with
   automatic CI remediation on the same PR, independent exact-head gates,
   safe releases, monitoring and continuous re-planning.
7. Advance L1 → L2 → L3 → L4 → L5 only after evidence and a **separate
   owner-approved** change. The existence of a live example does not
   confer autonomy or deployment rights.

The existing `onboard`/`bootstrap` commands operate on a target repository.
Automated creation of remote repositories, paid infrastructure, privileged
credentials, or hands-free implementation is **not** implied by these
steps. Those capabilities need independently tested, explicit adapters and
permissions; failing closed is preferable to pretending a project was made.

## Invariants for the distribution

- No real target repository URLs, named-project examples, deployment
  identifiers, project-specific state or target credentials in shipped
  OneCompany content.
- Example fixtures use synthetic `example/*` identities and test refusal
  paths as well as success paths.
- A framework upgrade never overwrites project-owned contracts or imports
  another project's state.
- Project-neutral orchestration and project-local implementation can interact
  through schema-validated manifests without making the product depend on
  any specific project.
