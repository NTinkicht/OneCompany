# OneCompany

**One human. A team of AI workers. One autonomous company.**

OneCompany is a reusable operating system for running software projects as governed autonomous, multi-agent companies from GitHub. It coordinates work, permissions, budgets, agent readiness, dispatch, leases, CI, independent review, merge integrity, state reconciliation, and round-the-clock liveness without binding the company to one model vendor.

OneCompany was shaped by real operating experience building Tabibi with ChatGPT, Codex, Claude, GitHub Copilot, Gemini CLI, Mistral Vibe, GitHub Actions, strict budget constraints, repeated failovers, CI incidents, and exact-head review/merge discipline.

## What it gives a project

- bounded Work Units and one canonical implementation stream;
- capability-level actor readiness rather than “provider is up/down” guesses;
- capability-specific routing after budget/permission/authorship filters;
- explicit executable dispatch/wake paths — routing is not mistaken for execution;
- durable distributed leases and cumulative material authorship;
- deterministic CI plus independent non-author exact-head review;
- durable exact-head gates outside the implementation SHA;
- expected-head mechanical merge;
- same-stream failover and race-safe first-valid-lease-wins coordination;
- zero-extra-spend and other explicit financial policies;
- project contracts for product, architecture, security, quality and operations;
- role overlays and Spotify-inspired aligned autonomy;
- context-efficiency/shadow-adoption patterns;
- unattended-agent templates that start disabled/read-only;
- L0-L5 autonomy;
- event-driven handoffs plus scheduled liveness reconciliation for 24/7 operation;
- self-validation, simulations and fresh-bootstrap smoke testing.

## Core loop

```text
live GitHub + durable coordination ledger
            ↓
reconcile
            ↓
select dependency-ready Work Unit
            ↓
route verified capability
            ↓
resolve a real dispatch/wake mechanism
            ↓
acquire one canonical implementation lease
            ↓
implement on one branch / PR
            ↓
deterministic CI
            ↓
independent exact-head gate
            ↓
expected-head merge
            ↓
reconcile / release / select next work
            ↓
repeat
```

## The control plane

```text
.onecompany/
  config.json       project + autonomy policy
  budget.json       spend/capacity policy
  actors.json       potential worker capabilities
  readiness.json    proved capability/access/current degradation
  routing.json      capability-specific preference order
  dispatch.json     executable wake/run mechanisms
  roles.json        durable role contracts
  ledger.json       durable GitHub coordination ledger policy
  supervision.json  round-the-clock liveness policy
  state.json        derived local/cache snapshot
  queue.json        dependency-ready work index
  patterns.json     reusable operating patterns
  overlays.json     specialist lens registry
  schemas/          machine schemas
  templates/        disabled provider/supervisor/project templates
```

The crucial distinction is:

```text
actors.json      = what an actor type could do
readiness.json   = what this configured installation has actually proved now
routing.json     = who is preferred after hard eligibility checks
dispatch.json    = how that actor can actually be started
ledger.json      = how independent runs share leases/authorship/gates
supervision.json = how the company notices missed/stale transitions
```

## 24/7 operation

OneCompany treats round-the-clock operation as a **liveness and coordination problem**, not a reason to wake every worker repeatedly.

> **Events move the company; schedules make sure no transition was missed.**

Recommended layers:

1. event-driven PR/CI/review/merge handoffs;
2. scheduled reconciliation as a safety net;
3. durable Team Room ledger shared by independent runs;
4. scheduler-health monitoring;
5. human escalation only for explicit human-only decisions.

A documented profile uses four hourly ChatGPT tasks staggered at approximately `:02`, `:17`, `:32`, and `:47` for an effective ~15-minute liveness cadence where current plan limits allow it. They are replicas of **one supervisor**, not four orchestrators. The durable ledger applies first-valid-lease-wins ordering so races cannot create two canonical writers.

See:

- [`docs/SCHEDULED-SUPERVISION.md`](docs/SCHEDULED-SUPERVISION.md)
- [`examples/chatgpt-scheduled-supervisors.md`](examples/chatgpt-scheduled-supervisors.md)
- [`docs/DURABLE-COORDINATION-LEDGER.md`](docs/DURABLE-COORDINATION-LEDGER.md)
- [`docs/DISPATCH-AND-WAKE.md`](docs/DISPATCH-AND-WAKE.md)

All supervisors and provider automations ship disabled by default.

## Start a new project

From a OneCompany checkout:

```bash
python onecompany.py bootstrap \
  --target /path/to/project \
  --repository owner/repo \
  --initialize-contracts
```

Then follow [`docs/SETUP-FROM-ZERO.md`](docs/SETUP-FROM-ZERO.md).

Before raising autonomy, run:

```bash
python onecompany.py doctor
python onecompany.py validate
python onecompany.py simulate
python onecompany.py simulate-supervision
python onecompany.py readiness --local-probe
python onecompany.py audit-github
python onecompany.py next-work
python onecompany.py supervise --force-observe
```

Then complete [`docs/FIRST-RUN-ACCEPTANCE.md`](docs/FIRST-RUN-ACCEPTANCE.md).

## Main commands

```text
doctor                 environment diagnostics
validate               cross-file policy validation
simulate               core policy simulations
simulate-supervision   liveness/scheduling simulations
readiness              local capability probes
 audit-github           GitHub configuration audit
next-work               dependency-ready work selection
route                   eligible actor selection
dispatch                executable mechanism resolution
ledger                  durable coordination read/post
lease                   acquire/release/transfer canonical implementation lease
gate                    exact-head independent gate
merge                   expected-head mechanical merge
reconcile               rebuild cache from live GitHub/ledger
supervise               liveness state decision
bootstrap               fresh-project installer
```

## Autonomy levels

| Level | Meaning |
| --- | --- |
| L0 | Manual |
| L1 | AI-assisted planning/work |
| L2 | Autonomous bounded implementation, human merge gate |
| L3 | Autonomous delivery with durable independent gate/merge |
| L4 | Continuous company: selects and continues dependency-ready work |
| L5 | Governed autonomous company including ongoing maintenance/incident/liveness operation |

L3+ autonomous delivery requires a durable coordination ledger in the reference model. L4+ additionally requires continuous supervision/no-idle readiness.

## Non-negotiable invariants

1. GitHub is operational source of truth.
2. One bounded WU has one canonical implementation stream.
3. A lease is explicit and durable for distributed autonomy.
4. First valid implementation lease wins concurrent claims.
5. Failover changes the worker, not the stream.
6. Material authors cannot sole-gate their exact head.
7. Required CI and independent judgment target the same SHA.
8. Merge verifies the approved SHA still equals the live head.
9. Routing does not equal execution; a real dispatch path must exist.
10. Unattended writers require the canonical active lease.
11. Ready work + no valid lease is a fault only when continuous autonomy says it should be working.
12. Budgets are policy; no silent paid fallback/overage/top-up/new vendor.
13. Secrets/sensitive data stay out of prompts, state, logs and coordination comments.
14. Human-only boundaries remain human-only until explicitly changed.
15. Role overlays are lenses, not identities/permissions.
16. Experimental infrastructure earns authority through evidence.
17. Scheduled supervisors supervise; they do not create extra implementation streams.
18. Local `state.json` is a cache, not durable multi-agent coordination truth.

## Design lineage

OneCompany explicitly documents what was adapted rather than inventing a mythology:

- Spotify-inspired aligned autonomy: temporary delivery squads, reusable discipline chapters, advisory guilds;
- Agency Agents-inspired specialist role overlays;
- Headroom-derived shadow-before-authority and deterministic-first context routing;
- Tabibi-native leases, failover, exact-head gates, capacity circuit breakers, evidence-over-activity, no-idle, Team Room coordination and scheduled stale-work reconciliation;
- later Spotify Honk work as convergent evidence, not retroactive origin.

See [`docs/DESIGN-LINEAGE.md`](docs/DESIGN-LINEAGE.md) and [`docs/REFERENCES.md`](docs/REFERENCES.md).

## Safety posture

The foundation deliberately starts conservative: L1, zero additional AI spend, workers disabled/unconfigured, durable ledger disabled, unattended provider paths disabled, and supervision disabled/observe-only. Authority is raised only after setup evidence and first-run drills.

OneCompany is not a promise that models are infallible and is not a requirement to buy six AI products. The operating system is meant to be stronger than any individual worker.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). OneCompany itself follows the same model: bounded work, deterministic CI, independent exact-head review, and no self-gating.
