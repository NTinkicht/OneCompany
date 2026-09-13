# OneCompany

**One human. A team of AI workers. One governed autonomous company.**

OneCompany is a reusable operating system for turning a GitHub repository into a multi-agent software company with explicit work ownership, deterministic verification, independent review, budget/security guardrails, real execution paths, durable cross-run coordination, and round-the-clock supervision.

It was shaped by real operating experience building Tabibi with ChatGPT, Codex, Claude, GitHub Copilot, Gemini CLI, Mistral Vibe, GitHub Actions, strict budget constraints, provider limits, failovers, CI incidents, and exact-head review/merge discipline.

## 60-second start

### If you created a repository from the OneCompany GitHub template

```bash
python onecompany.py init \
  --repository OWNER/REPO \
  --project-name "My Product" \
  --initialize-contracts

python onecompany.py check
python onecompany.py doctor
python onecompany.py status --live
```

### If you already have a product repository

From a trusted OneCompany checkout:

```bash
python onecompany.py bootstrap \
  --target /path/to/product \
  --repository OWNER/REPO \
  --project-name "My Product" \
  --initialize-contracts
```

Then configure GitHub protection, deterministic product CI, workers/readiness, routing/dispatch, and complete [`docs/FIRST-RUN-ACCEPTANCE.md`](docs/FIRST-RUN-ACCEPTANCE.md). Do **not** raise autonomy merely because configuration files exist.

Full setup: [`BOOTSTRAP.md`](BOOTSTRAP.md) and [`docs/SETUP-FROM-ZERO.md`](docs/SETUP-FROM-ZERO.md).

## What OneCompany provides

- bounded Work Units and one canonical implementation stream;
- explicit, durable implementation leases with first-valid-lease-wins race handling;
- capability-level readiness instead of provider-wide up/down guesses;
- capability routing after permission, budget and authorship filters;
- executable dispatch/wake paths — choosing an actor is not mistaken for starting it;
- cumulative material authorship across failover/replay/cherry-pick;
- deterministic CI plus independent non-author exact-head review;
- durable exact-head gates outside the implementation commit;
- merge-time revalidation of reviewer independence, evidence, CI and exact head;
- expected-head mechanical merge;
- same-stream failover;
- zero-extra-spend and other explicit financial policies;
- product contracts for product, architecture, security, deterministic quality, design/UX and operations;
- provider-neutral role overlays and Spotify-inspired aligned autonomy;
- deterministic-first context routing and shadow-before-authority adoption;
- disabled-by-default provider/supervisor templates;
- L0-L5 autonomy;
- event-driven handoffs plus scheduled liveness reconciliation;
- emergency stop, no-self-escalation and human control-plane sovereignty;
- schemas, validators, supply-chain audit, simulations and fresh-install smoke tests.

## The autonomous loop

```text
live GitHub + durable coordination ledger
             ↓
reconcile authoritative evidence
             ↓
select READY dependency-safe Work Unit
             ↓
route verified capability + budget + permission + independence
             ↓
resolve a real execution/dispatch mechanism
             ↓
acquire exactly one canonical implementation lease
             ↓
implement on one canonical branch / PR
             ↓
deterministic project CI
             ↓
independent exact-head gate
             ↓
merge-time revalidation + expected-head merge
             ↓
release / durable MERGED evidence / reconcile
             ↓
select next READY work at L4+
             ↓
repeat
```

`PROPOSED` means backlog/planning. `READY` means executable. Continuous autonomy never promotes an idea to implementation merely because the queue is otherwise empty.

## Machine control plane

```text
.onecompany/
  config.json        project/autonomy/safety policy
  governance.json    no-self-escalation + protected control-plane policy
  budget.json        spend/capacity policy
  actors.json        potential worker capabilities
  readiness.json     verified current capability/access/degradation
  routing.json       capability-specific preference order
  dispatch.json      executable wake/run mechanisms
  roles.json         durable company roles
  ledger.json        distributed GitHub coordination policy
  supervision.json   24/7 liveness policy
  state.json         local/reconciled cache only
  queue.json         Work Unit dependency graph
  patterns.json      reusable operating patterns
  overlays.json      specialist review/work lenses
  schemas/           machine contracts
  templates/         disabled provider/supervisor/project templates
```

Core distinction:

```text
actor declaration  != verified readiness
routing decision   != executable dispatch
heartbeat          != progress
local state        != durable distributed truth
PASS text          != valid current exact-head gate
scheduled task     != implementation lease
```

## Product and UI quality

OneCompany does not force React, Storybook, Playwright, Chromatic, or any paid stack. It requires **evidence appropriate to the product**.

Starter contracts:

- `PRODUCT.md` — user promise, scope and non-goals;
- `ARCHITECTURE.md` — boundaries, invariants, data/concurrency;
- `SECURITY.md` — auth/authz/privacy/trust boundaries;
- `QUALITY.md` — deterministic commands, reproducibility, flaky-test/retry policy;
- `DESIGN.md` — design system, complete UI states, accessibility, responsive behavior, localization/RTL, themes, visual regression and performance;
- `OPERATIONS.md` — deploy, observability, rollback, restore/recovery.

For web UI, the reference design contract targets WCAG 2.2 Level AA unless project/legal policy is stricter. Automated scans are useful evidence, not a substitute for semantic/keyboard/task-level review on important journeys.

See [`docs/UI-AND-EXPERIENCE-QUALITY.md`](docs/UI-AND-EXPERIENCE-QUALITY.md).

## 24/7 operation

> **Events move the company; schedules make sure no transition was missed.**

Recommended layers:

1. event-driven PR/CI/review/merge handoffs;
2. scheduled reconciliation as redundancy;
3. durable Team Room ledger shared by independent runs;
4. scheduler-health monitoring;
5. human escalation only for human-only decisions.

A Tabibi-derived profile uses four hourly ChatGPT tasks staggered around `:02`, `:17`, `:32`, and `:47`, yielding an effective ~15-minute supervisory cadence where platform limits allow. They are four replicas of **one supervisor**, not four orchestrators. Every run re-reads live GitHub and the durable lease; healthy work produces no duplicate implementation.

See [`docs/SCHEDULED-SUPERVISION.md`](docs/SCHEDULED-SUPERVISION.md), [`examples/chatgpt-scheduled-supervisors.md`](examples/chatgpt-scheduled-supervisors.md), [`docs/DURABLE-COORDINATION-LEDGER.md`](docs/DURABLE-COORDINATION-LEDGER.md), and [`docs/DISPATCH-AND-WAKE.md`](docs/DISPATCH-AND-WAKE.md).

All scheduled and provider automation ships disabled by default.

## Safety model

Reference defaults are conservative: L1, zero additional AI spend, all workers unconfigured/disabled, durable ledger disabled, unattended dispatch disabled, supervision disabled/observe-only.

Important safeguards:

- **Emergency stop:** freezes autonomous mutation while permitting read-only diagnosis/reconciliation and safe lease release.
- **No self-escalation:** an actor cannot grant itself credentials, budget, autonomy, reviewer independence, merge authority or trusted-publisher status.
- **Trusted base control plane:** a candidate PR changing governance/instructions is proposed data until merged; it cannot make its own weaker rules authoritative.
- **Human control-plane boundary:** reference policy requires human merge for protected OneCompany runtime/governance changes; constitution/governance policy are always-human paths.
- **Supply chain:** managed workflows reject floating external Actions, `pull_request_target`, and `permissions: write-all`.
- **Side effects:** idempotency/natural deduplication + bounded retries; destructive actions require recovery/rollback/compensation.
- **Budget:** quota exhaustion is capacity degradation, never automatic permission to spend.

Read [`company/CONSTITUTION.md`](company/CONSTITUTION.md), [`docs/TRUSTED-CONTROL-PLANE.md`](docs/TRUSTED-CONTROL-PLANE.md), and [`docs/INCIDENT-RUNBOOK.md`](docs/INCIDENT-RUNBOOK.md).

## Golden commands

```bash
# deterministic local acceptance — no provider call required
python onecompany.py check

# environment + live-account/repository reality
python onecompany.py doctor
python onecompany.py readiness --local-probe
python onecompany.py audit-github
python onecompany.py status --live

# observe liveness without enabling mutation
python onecompany.py supervise --force-observe
```

Main operational commands:

```text
init / bootstrap     safe project installation paths
check                full deterministic local acceptance suite
validate             schema + cross-file + governance + hardening validation
status               compact local/live operating view
next-work            READY-only dependency-safe selection
route                eligible actor selection
dispatch             real execution/wake mechanism resolution
ledger               durable coordination inspection/publication
lease                canonical lease acquire/release/transfer
gate                 exact-head independent verdict publication
merge                expected-head merge with reviewer/governance revalidation
reconcile            rebuild cache from authoritative evidence
supervise            liveness decision, not an extra implementer
```

## Autonomy levels

| Level | Meaning |
| --- | --- |
| L0 | Manual |
| L1 | Assisted planning/work |
| L2 | Autonomous bounded implementation, human merge |
| L3 | Autonomous product delivery inside policy with durable independent gate/merge |
| L4 | Continuous company that selects the next READY dependency-safe WU |
| L5 | Governed autonomous company including maintenance, incidents, planning and liveness |

L3+ requires the durable ledger in the reference model. L4+ additionally requires proven deterministic queue progression, no-idle reconciliation and continuous supervision. Governance/control-plane changes remain within the human merge boundary unless a prior human-approved stricter policy changes the model.

## Design lineage

OneCompany documents provenance rather than inventing mythology:

- Spotify-inspired aligned autonomy: temporary delivery squads, reusable discipline chapters, advisory guilds;
- Agency Agents-inspired specialist role overlays;
- Headroom-derived shadow-before-authority and deterministic-first context routing;
- Tabibi-native leases, same-stream failover, exact-head gates, capacity circuit breakers, evidence-over-activity, Team Room coordination, no-idle and scheduled stale-work reconciliation;
- later Spotify Honk work as convergent evidence, not retroactive origin.

See [`docs/DESIGN-LINEAGE.md`](docs/DESIGN-LINEAGE.md) and [`docs/REFERENCES.md`](docs/REFERENCES.md).

## Before production or public release

Complete [`docs/RELEASE-CHECKLIST.md`](docs/RELEASE-CHECKLIST.md). In particular, configure default-branch protection/required checks, choose the repository license, prove emergency stop/failover/stale-gate behavior, and enable the GitHub repository's **Template repository** setting if OneCompany is meant to be cloned through GitHub's template UX.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). OneCompany itself follows the same rules: bounded work, deterministic CI, independent exact-head review, no self-gating, and human promotion of protected control-plane changes.
