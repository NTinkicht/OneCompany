# OneCompany

**One human. A team of AI workers. One governed autonomous company.**

OneCompany is a reusable **CompanyOS** for running a software company from a GitHub repository. It combines strategy, requirements, planning, safe parallel execution, multi-agent routing, deterministic engineering assurance, independent review, release governance, continuous supervision and organizational learning without surrendering human sovereignty over critical decisions.

It uses provider-neutral capability routing, deterministic engineering evidence, strict budget limits, failover safety, and exact-head review discipline. It is not configured for any particular application, customer, or deployment.

## Start here

For a new **or existing** repository, the primary experience is one read-only-first command:

```bash
python onecompany.py onboard --target .
```

It inspects the repository, identifies the adoption mode, detects stack/tests/CI/contracts, shows collisions and proposes the safe installation path **without mutating anything**.

After reviewing the plan:

```bash
python onecompany.py onboard --target . --apply
```

Then:

```bash
python onecompany.py validate
python onecompany.py doctor
python onecompany.py plan summary
python onecompany.py status --live
```

See [`docs/ONBOARDING.md`](docs/ONBOARDING.md) for new-project, existing-project and template-copy flows.

## How CompanyOS works

The canonical end-to-end diagram is in [`docs/COMPANYOS-FLOW.md`](docs/COMPANYOS-FLOW.md).

```text
Human mission / sovereignty boundaries
              ↓
Approved strategy + requirements + risks
              ↓
Planning & Flow Engine
(priority + dependencies + critical path + safe parallel set)
              ↓
Capability Router
(budget + readiness + capacity + independence)
              ↓
One canonical stream per Work Unit
      ↙          ↓          ↘
    WU-A        WU-B       WU-C held
      ↓          ↓
  branch/PR  branch/PR
      ↓          ↓
 deterministic CI + engineering assurance
      ↓          ↓
 independent exact-head + exact-base gate
       ↘        ↙
          merge
            ↓
 release → observe → measure → learn
            ↓
      re-plan continuously
```

## Planning model

OneCompany does not force Scrum or SAFe. The hierarchy is flexible:

```text
Objective
  ↓
Epic
  ↓
Feature / Capability       optional
  ↓
User Story                 optional
  ↓
Formal Requirement
  ↓
Acceptance Criterion
  ↓
Work Unit
  ↓
Task / Enabler / Spike / Defect / Chore
  ↓
Test / Evidence / Release / Outcome
```

Formal requirements remain classified independently as `BR`, `UR`, `FR`, `NFR`, `SEC`, `DATA`, `OPS`, `UX`, and `CON`.

The versioned `.onecompany` graph is the approved machine baseline. GitHub Issues/Projects are the collaborative human UI. Editing issue prose does not silently re-baseline approved requirements, risks or scope.

## Safe parallel execution

OneCompany enforces **one canonical implementation stream per Work Unit**, not one stream for the entire company.

Independent WUs may run concurrently only when the planner can prove compatibility using:

- dependency relationships;
- declared write scopes;
- semantic resource locks;
- risk class;
- global WIP limits;
- per-actor verified implementation capacity.

Unknown scope fails closed to serialization. Critical-risk work serializes by default. The live PR diff is checked against the declared WU scope before a binding gate and again before merge.

Parallel merge safety is base-aware: a merge-ready gate records both the candidate **head SHA** and the **base SHA** it was validated against. If `main` moves, the previous integration evidence becomes stale and the branch must be updated/revalidated.

## What OneCompany provides

- strategy-to-execution portfolio graph;
- canonical requirements, acceptance criteria and risk registers;
- deterministic priority scoring, dependency analysis and critical-path visibility;
- conflict-safe parallel-set computation;
- bounded Work Units with one canonical writer per WU;
- durable implementation leases and first-valid-claim race handling;
- per-actor readiness and implementation-capacity constraints;
- capability routing after permission, budget, readiness and authorship filters;
- executable dispatch/wake paths — routing is not mistaken for execution;
- cumulative material authorship across failover/replay/cherry-pick;
- deterministic CI plus Engineering Excellence / OCES assurance;
- requirements quality, bidirectional traceability and risk governance;
- code quality, architecture fitness, testing, coverage, mutation and nonfunctional evidence;
- independent non-author exact-head/exact-base gates;
- expected-head merge with live scope and governance revalidation;
- stream-scoped failover, blockers and human-decision handling;
- zero-extra-spend and explicit budget policies;
- L0-L5 autonomy with no-self-escalation;
- event-driven handoffs plus scheduled liveness reconciliation;
- emergency stop and human control-plane sovereignty;
- fresh-install/bootstrap/self-test simulations;
- release/outcome learning loop.

## Machine control plane

```text
.onecompany/
  config.json                 project/autonomy/safety policy
  governance.json             protected control-plane policy
  budget.json                 spend/cost policy
  actors.json                 potential workers/capabilities
  readiness.json              verified capability/access/capacity
  routing.json                capability preference order
  dispatch.json               executable wake/run mechanisms
  roles.json                  durable company roles
  planning.json               hierarchy, priority and flow policy
  portfolio.json              objectives/epics/features/capabilities
  requirements-catalog.json   formal requirements + acceptance criteria
  risk-register.json          planning risks/treatments
  queue.json                  WUs/dependencies/scopes/locks/PR mapping
  ledger.json                 durable distributed coordination policy
  supervision.json            24/7 liveness policy
  state.json                  reconciled cache only
  quality*.json               engineering-quality policy/baselines
  architecture.json           declared architecture constraints
  traceability.json           assurance traceability policy
  schemas/                    machine contracts
  selftest/                   embedded CompanyOS self-tests
  reference/                  reference assurance evidence
```

Core distinctions:

```text
Issue discussion        != approved planning baseline
actor declaration       != verified readiness
routing decision        != executable dispatch
heartbeat               != progress
local state             != durable/live truth
PASS text               != valid current exact-head/base gate
scheduled supervisor    != implementation lease
READY work              != necessarily executable capacity
```

## Engineering assurance

OneCompany Engineering Standard / OCES makes quality evidence-based rather than model-opinion-based.

> An AI saying “the code looks good” is not quality evidence.

Depending on risk/profile, assurance may require static checks, unit/component/integration/contract/API/E2E/acceptance/regression/property/fuzz/mutation/security/migration/performance/reliability/accessibility/visual/compatibility/operations/AI-evaluation evidence.

Requirements, architecture, risks, tests and exact-SHA evidence are traceable. Waivers are explicit, owned and expiring; silent permanent suppressions are forbidden.

See [`docs/engineering/ENGINEERING_STANDARD.md`](docs/engineering/ENGINEERING_STANDARD.md).

## Autonomous loop

```text
reconcile live GitHub + durable ledger
              ↓
compute dependency-ready conflict-safe candidates
              ↓
rank / critical-path / WIP admission
              ↓
route verified capability + budget + capacity
              ↓
acquire one implementation lease per admitted WU
              ↓
execute independent streams concurrently
              ↓
CI + assurance + independent exact-head/base review
              ↓
merge one stream without destroying unrelated leases
              ↓
recompute graph / release newly unblocked work
              ↓
release → observe → outcome review → update baseline
              ↓
repeat when autonomy policy permits
```

`PROPOSED` is backlog/planning. `READY` is eligible for execution, but actual start still requires dependency, conflict, WIP, worker-capacity, budget and authority checks.

## 24/7 operation

> **Events move the company; schedules make sure no transition was missed.**

Recommended layers:

1. event-driven PR/CI/review/merge handoffs;
2. scheduled reconciliation as redundancy;
3. durable Team Room ledger shared by independent runs;
4. scheduler-health monitoring;
5. nightly/low-priority maintenance;
6. human escalation only for human-only decisions.

Scheduled supervisors are replicas of one liveness function, not extra implementers. They reconcile the portfolio and may fill available safe WIP slots; they never create duplicate writers for an existing WU.

See [`docs/SCHEDULED-SUPERVISION.md`](docs/SCHEDULED-SUPERVISION.md) and [`docs/DURABLE-COORDINATION-LEDGER.md`](docs/DURABLE-COORDINATION-LEDGER.md).

## Safety and sovereignty

Reference defaults remain conservative: L1, zero additional AI spend, workers unconfigured/disabled, unattended dispatch disabled, durable ledger disabled, and supervision observe-only.

Important safeguards:

- **Emergency stop** freezes autonomous mutation while permitting diagnosis/reconciliation and safe lease release.
- **No self-escalation** prevents workers from granting themselves credentials, budget, autonomy, reviewer independence or merge authority.
- **Trusted-base governance** means a control-plane PR cannot use its proposed weaker rules to approve itself.
- **Human-only decisions** remain human for budget policy, new credentials, legal/governance changes, destructive production actions, sensitive publication and critical-risk acceptance unless a prior reviewed policy explicitly delegates them.
- **Budget exhaustion** degrades capacity; it never silently enables paid fallback, overage, top-up or a new vendor.
- **Side effects** require idempotency/deduplication and bounded retries; destructive work requires tested recovery/rollback/compensation.

Read [`company/CONSTITUTION.md`](company/CONSTITUTION.md), [`docs/TRUSTED-CONTROL-PLANE.md`](docs/TRUSTED-CONTROL-PLANE.md), and [`docs/INCIDENT-RUNBOOK.md`](docs/INCIDENT-RUNBOOK.md).

## Golden commands

```bash
# adoption
python onecompany.py onboard --target .
python onecompany.py onboard --target . --apply

# deterministic acceptance + environment
python onecompany.py check
python onecompany.py validate
python onecompany.py doctor
python onecompany.py audit-github
python onecompany.py status --live

# planning
python onecompany.py plan summary
python onecompany.py plan validate
python onecompany.py plan rank
python onecompany.py plan parallel
python onecompany.py plan critical-path

# liveness / execution
python onecompany.py next-work
python onecompany.py route ...
python onecompany.py lease ...
python onecompany.py gate ...
python onecompany.py merge ...
python onecompany.py reconcile
python onecompany.py supervise --force-observe
```

Main commands include `onboard`, `init`, `bootstrap`, `check`, `validate`, `status`, `plan`, `next-work`, `route`, `dispatch`, `ledger`, `lease`, `gate`, `merge`, `reconcile`, `supervise`, `assurance`, `trace`, `risk`, and `evidence`.

## Autonomy levels

| Level | Meaning |
| --- | --- |
| L0 | Manual |
| L1 | Assisted planning/work |
| L2 | Autonomous bounded implementation, human merge |
| L3 | Autonomous product delivery inside policy with durable independent gate/merge |
| L4 | Continuous company that keeps safe dependency-ready WIP flowing |
| L5 | Governed autonomous company including delivery, maintenance, incidents, planning and liveness |

Higher autonomy never lowers quality, evidence, budget or governance requirements.

## Before public/production release

Complete [`docs/RELEASE-CHECKLIST.md`](docs/RELEASE-CHECKLIST.md). Two repository-owner items are intentionally not decided by autonomous workers:

1. choose the repository license before public open-source release;
2. configure/verify default-branch protection and required checks in GitHub administration.

Those are tracked as human decisions rather than being silently guessed.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). OneCompany itself follows the same principles: bounded work, deterministic CI, conflict-safe parallelism, cumulative authorship, independent exact-head/base review, no self-gating and human promotion of protected control-plane changes.
