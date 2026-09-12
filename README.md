# OneCompany

**One human. A team of AI workers. One autonomous company.**

OneCompany is a reusable operating system for running software projects as autonomous, multi-agent companies from GitHub. It turns a repository into a governed organization: work is decomposed into bounded units, routed by **verified capability**, leased to one implementer, verified by deterministic CI, independently reviewed on the exact commit, merged, reconciled, and followed by the next dependency-ready unit of work.

OneCompany was designed from real operating experience building Tabibi with ChatGPT, Codex, Claude, GitHub Copilot, Gemini CLI, Mistral Vibe, GitHub Actions, and strict zero-extra-spend constraints. It is intentionally provider-neutral: **roles belong to the company, not to model brands.**

## The promise

OneCompany gives a project a reusable control plane for:

- multi-agent orchestration without duplicate implementation streams;
- capability-based routing, capability-level readiness, and explicit work leases;
- automatic failover when one capability is unavailable, quota-limited, or unsuitable;
- independent non-author review and exact-head merge gates;
- deterministic CI as the technical referee;
- machine-readable company state, queue, actors, readiness, routing, supervision, roles, patterns, overlays, and budgets;
- no-idle detection when ready work exists but nobody holds a valid lease;
- cost and capacity governance, including a hard zero-extra-spend mode;
- privacy, secret, permission, logging, and untrusted-input boundaries;
- provider-by-provider installation/authentication/smoke-test guidance;
- disabled-by-default unattended agent and supervisor templates;
- 24/7 liveness supervision using event-driven handoffs plus scheduled reconciliation;
- migration into existing repositories, upgrade guidance, simulation and first-run company acceptance tests.

## Core loop

```text
Observe repository reality
        ↓
Reconcile declared state with GitHub
        ↓
Select smallest dependency-ready Work Unit
        ↓
Route verified capability + budget + access + authorship
        ↓
Grant exactly one implementation lease
        ↓
Implement on one canonical branch / PR
        ↓
Run deterministic CI
        ↓
Independent exact-head review
        ↓
Remediate on the same stream if needed
        ↓
PASS — MERGE_READY
        ↓
Merge with expected-head protection
        ↓
Reconcile state and release leases
        ↓
Select next ready work
        ↓
Repeat
```

Autonomy does **not** mean every actor edits everything. OneCompany separates authority: implementation, deterministic verification, independent judgment, merge execution, supervision, and human decisions are distinct responsibilities.

## 24/7 operation

OneCompany treats round-the-clock operation as a liveness problem, not a reason to wake every agent repeatedly.

```text
repository event
    ↓
event-driven handoff
    ↓
next bounded capability

        plus

scheduled supervisor
    ↓
reconcile live GitHub
    ↓
repair a missed/stale transition only when evidence requires it
```

The optional schedule profiles include an hourly GitHub Actions supervisor and a **four-staggered-hourly ChatGPT supervisor mesh** at approximately `:02`, `:17`, `:32`, and `:47`, producing an effective ~15-minute reconciliation cadence while each ChatGPT task itself runs only hourly. The four tasks are replicas of one supervisor, not four competing orchestrators; leases and live state make repeated checks idempotent.

Read [`docs/SCHEDULED-SUPERVISION.md`](docs/SCHEDULED-SUPERVISION.md) before enabling any continuous supervisor. The safe foundation starts supervision disabled and observe-only.

## Built from proven and adapted patterns

OneCompany records its design lineage instead of pretending the model appeared from nowhere.

- **Spotify-inspired aligned autonomy:** temporary bounded squads, discipline chapters, advisory guilds.
- **Agency Agents-inspired role overlays:** specialist lenses without fake extra actors or authority.
- **Headroom-inspired shadow adoption:** experimental context infrastructure proves itself beside original evidence before promotion.
- **Tabibi-native coordination:** single-stream leases, orthogonal parallelism, exact-head two-key gates, capacity circuit breakers, evidence-over-activity, expected-head merge, failover that preserves the stream, and scheduled stale-work reconciliation.

See [`patterns/`](patterns/README.md), [`overlays/`](overlays/README.md), [`docs/DESIGN-LINEAGE.md`](docs/DESIGN-LINEAGE.md), and [`docs/REFERENCES.md`](docs/REFERENCES.md).

## Start here

For a brand-new deployment, use **[`docs/SETUP-FROM-ZERO.md`](docs/SETUP-FROM-ZERO.md)**.

1. Bootstrap the control plane.
2. Set repository identity, budget, CI contract, and initial L1/L2 autonomy.
3. Configure GitHub protections/permissions.
4. Configure only the workers you actually own using [`docs/agent-setup/`](docs/agent-setup/README.md).
5. Record proven capabilities/access in `.onecompany/readiness.json`.
6. Review `.onecompany/routing.json` and `.onecompany/supervision.json`.
7. Run:

```bash
python onecompany.py doctor
python onecompany.py validate
python onecompany.py simulate
python onecompany.py simulate-supervision
python onecompany.py readiness --local-probe
python onecompany.py audit-github
python onecompany.py supervise --force-observe
```

8. Complete [`docs/FIRST-RUN-ACCEPTANCE.md`](docs/FIRST-RUN-ACCEPTANCE.md).
9. Start the first real Work Unit.
10. Enable unattended paths, scheduled supervision, or L3+ only after the relevant drills are green.

For an existing repository, also read [`docs/MIGRATION.md`](docs/MIGRATION.md) and [`docs/UPGRADING.md`](docs/UPGRADING.md).

## Agent setup

Detailed setup runbooks cover ChatGPT, Codex, Claude/Claude Code, GitHub Copilot, Gemini CLI, Mistral Vibe, a human owner and custom/local workers. See [`docs/AGENT-CONFIGURATION-MATRIX.md`](docs/AGENT-CONFIGURATION-MATRIX.md).

```text
actors.json       = potential capability
readiness.json    = configured + smoke-tested capability/access now
routing.json      = preference after hard eligibility filters
supervision.json  = round-the-clock liveness policy
```

## Autonomy levels

| Level | Name | What OneCompany may do |
|---|---|---|
| L0 | Manual | Documentation/state only; humans execute all work. |
| L1 | Assisted | AI proposes plans and patches; humans authorize execution. |
| L2 | Autonomous Implementation | AI may implement bounded Work Units; humans gate merge. |
| L3 | Autonomous Delivery | Implementation, CI remediation, independent review, and merge can run autonomously inside policy. |
| L4 | Continuous Company | The company selects the next ready Work Unit and continues without idle gaps. |
| L5 | Governed Autonomous Company | Product delivery, maintenance, incident response, capacity failover, state reconciliation, planning and supervision run continuously with explicit human-only decision classes. |

## Non-negotiable invariants

1. GitHub is operational source of truth.
2. One Work Unit has one canonical implementation stream.
3. A lease is explicit.
4. Failover keeps the stream.
5. Material authors cannot sole-gate their head.
6. Reviews target an exact SHA.
7. Green CI is necessary, not sufficient.
8. Merge uses expected-head protection.
9. Ready work + no valid lease is an operational fault at continuous autonomy.
10. Budgets are policy; no silent paid fallback/overage/top-up/new vendor.
11. Secrets and sensitive data stay out of prompts/logs/state/issues/comments.
12. Human-only boundaries remain human-only until explicitly changed.
13. Role overlays are lenses, not identities.
14. Experimental infrastructure earns authority through evidence.
15. Declared capability is not verified readiness.
16. **Scheduled supervisors are supervisors, not extra implementers.** They must reconcile live evidence and cannot create duplicate streams or bypass budget/review/human boundaries.

## Repository map

```text
.onecompany/
  config.json         project/autonomy policy
  actors.json         potential worker capabilities
  readiness.json      verified surfaces/capabilities/access/current degradation
  routing.json        capability-specific preference order
  supervision.json    continuous liveness/scheduling policy
  roles.json          role contracts
  budget.json         spend/capacity policy
  state.json          reconciled operational cache
  queue.json          dependency-ready work index
  patterns.json       reusable operating patterns
  overlays.json       specialist overlay registry
  schemas/            control-plane schemas
  templates/          disabled provider/supervisor templates
agents/                worker behavior adapters
company/               constitution
patterns/              reusable organizational/technical patterns
overlays/              specialist professional lenses
docs/agent-setup/      provider setup runbooks
docs/                  setup, scheduling, security, migration, upgrades, runbooks
scripts/               validation, routing, leases, gates, merge, reconcile, supervise
.github/                issue/PR templates and active validation workflow
examples/               reference examples
```

## What OneCompany is not

OneCompany is not a promise that models are infallible, a hidden swarm that bypasses review, a requirement to buy six AI products, or a scheduler that manufactures busywork. Legitimate idle is allowed when no dependency-ready work exists.

## The design principle

> **Replace clever coordination with explicit contracts that can be checked.**

The strongest model should spend its context solving the product problem, not rediscovering ownership, current head, stale reviews, budget, permissions, or whether another worker is already doing the same job.

## Status

The `0.1.0-foundation` baseline starts safe: actors unconfigured, spend cap zero, unattended provider workflows and supervisors disabled, supervision observe-only, and autonomy low. A deployment becomes autonomous by proving capability and deliberately raising authority.

## Contributing

Start with [`CONTRIBUTING.md`](CONTRIBUTING.md), then follow OneCompany itself: bounded Work Unit, single implementation lease, deterministic CI, independent exact-head review, expected-head merge, and evidence-based supervision.
