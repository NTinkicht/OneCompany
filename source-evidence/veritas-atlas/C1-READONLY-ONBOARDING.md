# Veritas Atlas C1 Read-Only Onboarding

Status: **READ-ONLY / NOT MUTATION READY**

Target: `NTinkicht/veritas-atlas`  
Observed default branch: `main`  
Observed main SHA: `e19a0780ec8d5237d923f6d1cdb3a4af24346c95`  
Observation date: 2026-09-18  
Target writes performed by this onboarding: **none**

This report is evidence and adoption planning only. It grants no lease, dispatch, merge, deployment, branch-protection, workflow, or target-mutation authority.

## Executive result

Veritas Atlas is a substantially cleaner first proving ground than Tabibi from a coordination perspective: no open pull request or issue was observed, no repository workflow files were observed, and there is no inherited OneCompany control plane to unwind.

That simplicity must not be confused with readiness. The current repository lacks a verified protected promotion boundary and repository-native exact-head CI. Runtime/deployment mutation ownership is still unknown. Development authentication and secret defaults are present in source. The current test estate is mainly script-driven, and one documented health-check contract is not visible in the API bootstrap.

**C1 conclusion: Veritas Atlas is suitable for continued OneCompany onboarding, but it is not ready for C2 mutation or C2b cutover.**

## Exact-state snapshot

The companion machine-readable snapshot is:

`source-evidence/veritas-atlas/c1-snapshot.json`

Observed live GitHub facts:

- repository is private and the owner has administrative access;
- default branch is `main`;
- exact observed main is `e19a0780ec8d5237d923f6d1cdb3a4af24346c95`;
- GitHub reports `main` as not protected;
- the repository ruleset query returned an empty set;
- no open pull request was returned;
- repository metadata reported zero open issues;
- no `.github/workflows` path exists in the observed main tree.

The absence of repository workflow files is **not** proof that no external deployment service, webhook, scheduled job, human script, or other mutator exists. That inventory remains explicitly unresolved.

## Current product topology

### Backend

The solution contains four .NET 10 projects:

- `VeritasAtlas.Api`
- `VeritasAtlas.Application`
- `VeritasAtlas.Domain`
- `VeritasAtlas.Infrastructure`

The persistence layer uses EF Core with Npgsql/PostgreSQL. Database migrations are present, including the initial migration and a contradiction-slice migration.

No .NET test project was observed in the repository tree.

### Frontend

The strongest current frontend candidate is `apps/web/veritas-atlas-web`, using React 19, TypeScript, Vite, React Router, and TanStack React Query.

A separate root-level `frontend/` tree also exists. It contains a much smaller dashboard/cases/login surface. C1 cannot safely decide whether it is obsolete, experimental, or independently used. It must remain an explicit topology blocker until provenance identifies the canonical frontend.

### Historical diagnostic material

The `_diagnostics/` tree contains hundreds of historical captures and phase reports. Those files are useful evidence but must not be treated as live product state or control-plane authority.

The root README is also stale relative to the observed tree: it describes directories such as `services/workers`, `infra/docker`, `infra/scripts`, `docs`, and shared packages that are not present in the live tree. Future planning must use exact live paths rather than README topology assumptions.

## Build and quality boundary

Observed build surfaces:

- backend: .NET 10 solution/projects;
- frontend: `npm run build` and `npm run lint`;
- smoke tests: PowerShell scripts under `tests/smoke`;
- additional workflow test script: root `test.ps1`.

Important gaps:

1. **No repository-native CI workflow.** There is no observed GitHub Actions workflow to bind build/test evidence to an exact PR head.
2. **No .NET test project.** Current backend assurance appears heavily script/integration based.
3. **Health contract unresolved.** The smoke pack and frontend call `/health` and `/health/db`, but the observed `Program.cs` does not visibly register/map health checks and no backend health controller was found.
4. **No protected default branch.** A green build alone would not create an adequate promotion boundary.

These are C2 planning blockers, not invitations to change the target during C1.

## Authentication and secret boundary

The current code contains development scaffolding that must be separated from any future production authority:

- `Program.cs` and `JwtTokenService.cs` contain a fallback JWT signing secret intended for development;
- `DevUserStore.cs` contains fixed development users for operator, reviewer, publisher, and admin roles using a shared development password;
- root `test.ps1` defaults to the same development admin credential;
- `appsettings.json` includes a local PostgreSQL development connection string;
- JWT bearer configuration currently sets `RequireHttpsMetadata = false`.

C1 does **not** classify these as exposed production credentials because deployment/runtime configuration has not been verified. It does classify them as **production-readiness blockers**: OneCompany must not promote or deploy a target while production identity, secret injection, HTTPS, and database credential boundaries remain unknown.

## Mutation-writer inventory

Current status: **UNVERIFIED**

Observed repository-native mutation machinery:

- no `.github/workflows` files;
- no existing OneCompany control plane;
- no open PR stream.

Not yet verified:

- external deployment services;
- webhooks;
- scheduled jobs outside the repository;
- scripts run manually or by another host;
- database migration automation;
- hosting provider auto-deploy;
- any other bot/service account with write/deploy authority.

Therefore C1 does **not** assert “zero incumbents.” A later verified empty-writer finding is allowed by the generic C2a/C2b gates, but it must be evidenced explicitly.

## Adoption classification

### Preserve

- existing domain/application/infrastructure layering;
- EF Core migrations and PostgreSQL persistence contract;
- active React/Vite frontend once canonical path is proven;
- useful smoke/workflow scenarios as candidate regression specifications;
- publication/review governance concepts already represented in the product.

### Adapt

- development auth configuration into explicit dev vs production identity boundaries;
- smoke scripts into deterministic CI-safe tests;
- health contract into a verified backend/runtime contract;
- current repository topology documentation;
- current backlog/history into bounded OneCompany objectives and Work Units.

### Add later, through reviewed C2 changes

- protected default-branch promotion boundary;
- exact-head CI for backend/frontend/tests;
- OneCompany control-plane files;
- target-specific write scopes and resource locks;
- explicit runtime/deployment ownership;
- secret/environment policy;
- rollback/deployment evidence;
- canonical Work Unit backlog.

### Retire later, only after provenance review

- stale root `frontend/` if proven superseded;
- stale README topology claims;
- historical diagnostic artifacts that should be archived or excluded from active planning;
- development-only auth defaults from any production execution path.

Nothing in the “retire” category is deleted during C1.

## Candidate future Work Units

These are planning candidates only; none is authorized or started here.

- **V-C2a-01 — Shadow adoption manifest:** generalize the C2a target model for an idle repository with no fabricated PR/WU stream.
- **V-C2a-02 — Mutation/deployment ownership proof:** establish whether the incumbent writer inventory is truly empty.
- **V-C2a-03 — Promotion-boundary design:** propose branch protection/rules + human review without applying them.
- **V-C2a-04 — Deterministic CI design:** specify .NET build/test, frontend build/lint, and bounded integration/smoke checks.
- **V-C2a-05 — Production auth/secrets boundary:** specify removal/containment of development defaults from production.
- **V-C2a-06 — Canonical topology cleanup plan:** resolve the two frontend trees, stale README claims, and diagnostic-history treatment.
- **V-C2a-07 — Runtime/deployment evidence:** identify hosting, database, deployment, rollback, and health ownership.

## Fail-closed blockers

C1 carries the following blockers forward:

- `DEFAULT_BRANCH_UNPROTECTED`
- `NO_REPOSITORY_CI_WORKFLOW`
- `NO_DOTNET_TEST_PROJECT`
- `HEALTH_CONTRACT_UNRESOLVED`
- `TOPOLOGY_DOCUMENTATION_DRIFT`
- `SECONDARY_FRONTEND_UNRESOLVED`
- `MUTATION_WRITER_INVENTORY_UNVERIFIED`
- `DEPLOYMENT_RUNTIME_OWNERSHIP_UNVERIFIED`
- `PRODUCTION_AUTH_SECRET_BOUNDARY_UNVERIFIED`

These blockers mean:

- C1 may complete as a read-only evidence stage;
- C2a may begin as **shadow planning only**;
- no Veritas target mutation is authorized;
- no C2b cutover-ready state may be claimed yet.

## Provenance rule

Every consequential target fact must be refreshed before later mutation. This report is bound to the exact observed Veritas Atlas main SHA above. If `main`, branch policy, open work, runtime ownership, or deployment state changes, the relevant evidence must be reconciled again.

Historical Tabibi evidence remains in its own namespace and is not reused as Veritas truth.
