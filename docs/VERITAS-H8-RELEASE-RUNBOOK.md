# Veritas Atlas H8 — staging release and recovery contract

**Status: blocked / planning-only.** Exact observed Veritas default-branch SHA
`a0cd9230b68b7a5b4fd6c9392b9f748afb49bfb0` (PR #6 merged).
Machine-readable evidence:
[`evidence/veritas/h8-release-rollback-2026-09-19.json`](../evidence/veritas/h8-release-rollback-2026-09-19.json).
The pending `veritas-db-readiness-contract` PR #7 is a **candidate**, not a
deployed endpoint, until independently reviewed, merged, explicitly released,
and verified.

## Exact infrastructure boundary

- Render selected workspace: `tea-d9cm2fnavr4c739vvl50`.
- API: `srv-dan1pqbtqb8s73a979s0`, recorded first live deploy
  `dep-dan1pqrtqb8s73a97bag`.
- Web: `srv-dan1pqjtqb8s73a979tg`, recorded first live deploy
  `dep-dan1pqrtqb8s73a97b00`.
- Both deployed from Veritas
  `47bd085cb5e75d4b72acffc7a9e1e54300a61977` with auto-deploy **OFF**.
  More recent GitHub merges are not proof that Render released them.
- Dedicated Neon: **Veritas Atlas Staging**,
  `quiet-bar-44039561`, DB `veritas_atlas`, branch
  `br-calm-wildflower-b1lw0zuf`; 13 app tables + EF history; two migrations.
  Do not access Project HUMAN or any other database.
- This operator playbook does not grant OneCompany a mutation lease, merge,
  deployment or database-migration authority.

## Release ownership and authorization

The owner (Nassim) is the staging release go/no-go and recovery decision
authority until H7/H8 record a reviewed, scoped delegation. An approved code PR
does **not** authorize a Render deploy. A first or future schema migration
requires its own specific database and migration go/no-go; it does not follow
from application-release approval. Budget and emergency-stop boundaries apply
regardless of who initiates a deploy. No paid resource or overage fallback.

A release record must identify the **exact** candidate and base SHAs,
independent exact-head review, required CI job results, immutable Render
image/static artifact digest where available, source SHA, deploy IDs, service
IDs, non-secret configuration revision, deployment start/finish times, named
operator/authorizer, schema migration IDs, and the known-good compatible
previous release. A bare 'live' or generic green CI status is not enough.

## Preflight — no environment mutation

1. Confirm GitHub promotion controls from actual administration/ruleset
   evidence, exact-head review, unresolved threads and required checks. H1
   remains blocked until independently verified.
2. Reconcile H7 external writers and scheduled/human deployment scripts.
   Keep unobserved scopes blocked; do not assert zero external writers.
3. Confirm Render API/web service IDs and auto-deploy status in the selected
   workspace. Identify the **last deploy that actually passed health plus
   operator smoke**, not just a previous GitHub commit.
4. Verify the dedicated Neon project/database and recorded applied EF
   migrations; capture a real recoverability point for any separately approved
   schema change. A Neon temporary schema test or history retention alone
   is not proof that lossless recovery was rehearsed.
5. Confirm the JWT/database/bootstrap credentials reside only in protected
   environment configuration or password manager; document revision
   identifiers, **never** their values or bearer tokens.
6. Freeze new scope if an emergency stop, reviewer/capacity failure, competing
   writer, stale head, red check, unexpected paid resource or schema drift
   appears. Read-only status and diagnosis may continue.

## Manual staging release (once specifically authorized)

1. Verify application/database compatibility with the currently deployed
   frontend/API and applied schema. If a new schema version is needed, stop:
   obtain an independent SQL review and a **separate** migration go/no-go.
2. Start only the `veritas-atlas-api-ntinkicht` release from the intended
   exact reviewed source commit. Record Render deployment ID/source commit
   and build digest. Auto-deploy remains off.
3. Probe `GET /health/live` and credential-free HTTP auth boundaries.
   On a release containing PR #7, separately probe `GET /health/ready`:
   HTTP 200 indicates PostgreSQL connectivity; HTTP 503 fails readiness.
   Do not repoint Render's liveness restart probe to database readiness.
4. Operator privately performs bootstrap login and `GET /api/v1/auth/me`,
   then a non-destructive **authenticated database-backed read**. Record
   pass/fail, response category and time without logging credentials,
   tokens or sensitive record contents. A public ready endpoint alone does
   not establish authenticated or schema-level behavior.
5. Release the static frontend **only if needed** for an independently
   reviewed compatible web change; record separate deploy ID/digest. Verify
   home, deep-link refresh, CORS and representative browser flow.
6. Observe for failures, then record release evidence in OneCompany with
   correct exact deployed commit(s) and observed environment. Do not claim
   OneCompany H8 or cutover is clear from a successful deploy alone.

## Failure, containment and rollback

If either service or the operator smoke fails, halt further releases and
retain API/web logs without publishing secrets. For a changed frontend,
restore its last **verified compatible** successful Render deploy first;
for a changed API, restore its previously verified compatible deploy.
Validate both service commit IDs and the unchanged current DB schema after
each recovery action. When only one initial Render deploy exists, there is
**no earlier verified service release to roll back to**; a proposed
revert/rebuild requires separate reviewed code and a recovery authorization.

Do not assume rolling back application code undoes a schema migration.
No reverse migration, table deletion, branch restore, project deletion or
data rewrite is included in this playbook's authority. For schema incidents
preserve state, review Neon recoverability within its actual retention
window, select a compatible forward fix or restore with owner approval,
define data-loss/risk tradeoffs explicitly, and test on an isolated branch
before affecting staging. The first migration was owner-authorized and is
already applied; no further schema write is preauthorized.

A failed/no-longer-trusted deployment can justify pausing new releases,
revoking the relevant scoped credentials, or stopping the **two identified
Veritas services** under the owner's specific incident decision. Never
disable or alter unrelated HUMAN or lego-teddy resources.

## Exit evidence still needed for H8

Actual operator-authenticated and DB-backed end-to-end smoke; reviewed
service rollback/recovery drill; immutable artifact/config revision; scoped
operator/writer inventory including non-connected hosting; exact-head
protected-main GitHub administration evidence; a reviewed migration
compatibility/backup strategy and RPO/RTO. Only OneCompany's trusted
policy authority can transition H8 after this evidence is independently
reviewed. A human authorization to release one application commit is not an
autonomy-level increase.
