# OneCompany

**One human. A team of AI workers. One autonomous company.**

OneCompany is a reusable operating system for running software projects as autonomous, multi-agent companies from GitHub. It turns a repository into a governed organization: work is decomposed into bounded units, routed by **verified capability**, leased to one implementer, verified by deterministic CI, independently reviewed on the exact commit, merged, reconciled, and followed by the next dependency-ready unit of work.

OneCompany was designed from real operating experience building Tabibi with ChatGPT, Codex, Claude, GitHub Copilot, Gemini CLI, Mistral Vibe, GitHub Actions, and strict zero-extra-spend constraints. It is intentionally provider-neutral: **roles belong to the company, not to model brands.**

## The promise

OneCompany gives a project a reusable control plane for:

- multi-agent orchestration without duplicate implementation streams;
- capability-based routing, **capability-level readiness**, and explicit work leases;
- automatic failover when one capability is unavailable, quota-limited, or unsuitable;
- independent non-author review and exact-head merge gates;
- deterministic CI as the technical referee;
- machine-readable company state, queue, actors, readiness, roles, patterns, overlays, and budgets;
- no-idle detection when ready work exists but nobody holds a valid lease;
- cost and capacity governance, including a hard zero-extra-spend mode;
- privacy, secret, permission, logging, and untrusted-input boundaries;
- provider-by-provider installation/authentication/smoke-test guidance;
- disabled-by-default unattended agent templates;
- human override points for decisions that should never be silently automated;
- migration into existing repositories without rewriting the product;
- simulation, diagnostics, GitHub configuration audit, and first-run company acceptance tests.

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

Autonomy does **not** mean every actor edits everything. OneCompany separates authority: implementation, deterministic verification, independent judgment, merge execution, and human decisions are distinct responsibilities.

## Built from proven and adapted patterns

OneCompany records its design lineage instead of pretending the model appeared from nowhere.

- **Spotify-inspired aligned autonomy:** Tabibi's Epic restructuring adapted temporary squads, discipline chapters, and advisory guilds. OneCompany keeps the alignment/autonomy principle and rejects cargo-cult ceremony.
- **Agency Agents-inspired role overlays:** specialist profiles sharpen a real worker's lens without creating fake extra employees, leases, permissions, or reviewer independence.
- **Headroom-inspired shadow adoption:** experimental context infrastructure is evaluated read-only beside original evidence before it may gain authority.
- **Tabibi-native coordination patterns:** single-stream leases, orthogonal parallelism, exact-head two-key gates, capacity circuit breakers, evidence-over-activity, expected-head merge, and failover that preserves the stream.

The catalog lives in [`patterns/`](patterns/README.md), overlays in [`overlays/`](overlays/README.md), and provenance in [`docs/DESIGN-LINEAGE.md`](docs/DESIGN-LINEAGE.md) / [`docs/REFERENCES.md`](docs/REFERENCES.md).

Spotify's later Honk background-agent work is documented as **related modern evidence**, not retroactive origin.

## Start here

For a brand-new deployment, use **[`docs/SETUP-FROM-ZERO.md`](docs/SETUP-FROM-ZERO.md)**.

For the compact path:

1. Read [`BOOTSTRAP.md`](BOOTSTRAP.md).
2. Bootstrap the control plane into your project.
3. Set repository identity, budget, CI contract, and initial L1/L2 autonomy.
4. Configure GitHub protections/permissions.
5. Follow [`docs/agent-setup/README.md`](docs/agent-setup/README.md) for every worker you actually own.
6. Record proven surfaces/capabilities/access in `.onecompany/readiness.json` — owning a subscription is not readiness.
7. Run:

```bash
python onecompany.py doctor
python onecompany.py validate
python onecompany.py simulate
python onecompany.py readiness --local-probe
python onecompany.py audit-github
```

8. Complete [`docs/FIRST-RUN-ACCEPTANCE.md`](docs/FIRST-RUN-ACCEPTANCE.md).
9. Create the first real Work Unit, one implementation lease, one canonical PR, deterministic CI, and an independent exact-head gate.
10. Enable unattended paths or L3+ only after the relevant drills are green.

For an existing repository, also read [`docs/MIGRATION.md`](docs/MIGRATION.md).

## Agent setup

OneCompany ships detailed setup runbooks for:

```text
ChatGPT
Codex
Claude / Claude Code
GitHub Copilot
Gemini CLI
Mistral Vibe
custom/local workers
```

See [`docs/AGENT-CONFIGURATION-MATRIX.md`](docs/AGENT-CONFIGURATION-MATRIX.md) and [`docs/agent-setup/`](docs/agent-setup/README.md).

Important distinction:

```text
actors.json     = potential capability
readiness.json  = configured + smoke-tested capability/access now
```

This is what lets the company represent “Codex review quota exhausted but implementation still works” without disabling Codex entirely.

## Autonomy levels

| Level | Name | What OneCompany may do |
|---|---|---|
| L0 | Manual | Documentation/state only; humans execute all work. |
| L1 | Assisted | AI proposes plans and patches; humans authorize execution. |
| L2 | Autonomous Implementation | AI may implement bounded Work Units; humans gate merge. |
| L3 | Autonomous Delivery | Implementation, CI remediation, independent review, and merge can run autonomously inside policy. |
| L4 | Continuous Company | The company selects the next ready Work Unit and continues without idle gaps. |
| L5 | Governed Autonomous Company | Product delivery, maintenance, incident response, capacity failover, state reconciliation, and planning run continuously with explicit human-only decision classes. |

See [`docs/AUTONOMY-LEVELS.md`](docs/AUTONOMY-LEVELS.md).

## Non-negotiable invariants

1. **GitHub is the operational source of truth.** Chat, Slack, memory, dashboards, and local notes are mirrors/attention layers.
2. **One Work Unit has one canonical implementation stream.**
3. **A lease is explicit.** Ownership is never inferred from activity alone.
4. **Failover keeps the stream.** Worker changes; branch/PR/objective/history stay.
5. **The author cannot be the sole independent gate.**
6. **Reviews target an exact SHA.** Material changes stale the old gate.
7. **Green CI is necessary, not sufficient.**
8. **Merge uses expected-head protection.**
9. **Ready work + no valid lease = operational fault at continuous autonomy.**
10. **Budgets are policy.** No silent paid fallback/overage/top-up/new vendor.
11. **Secrets/sensitive data stay out of prompts, logs, state, issues, and PR comments.**
12. **Humans keep authority over irreversible, regulated, financial, credential, production-destructive, and policy-changing actions unless explicitly delegated.**
13. **Role overlays are lenses, not identities.**
14. **Experimental infrastructure earns authority through evidence.**
15. **Declared capability is not verified readiness.** Routing requires the actual execution surface, capability, permission, budget, and current availability to be proven.

## Repository map

```text
.onecompany/                 Machine-readable company control plane
  config.json                Project/autonomy configuration
  actors.json                Potential worker capabilities
  readiness.json             Verified surfaces/capabilities/access/current degradation
  roles.json                 Role contracts and routing requirements
  patterns.json              Reusable operating-pattern catalog
  overlays.json              Specialist role-overlay registry
  state.json                 Reconciled operational cache
  queue.json                 Work Unit dependency queue
  budget.json                Spend/capacity policy
  schemas/                   Control-plane schemas
  templates/                 Disabled/reference provider setup/wake templates
agents/                      Worker behavior adapters
company/                     Constitution
patterns/                    Organizational/technical patterns
overlays/                    Specialist professional lenses
docs/agent-setup/            Provider install/auth/permission/smoke runbooks
docs/                        Architecture, setup, security, migration, runbooks
scripts/                     Validation, readiness, routing, reconciliation, audits
.github/                     Active safe templates/workflows
examples/                    Reference examples
```

## What OneCompany is not

OneCompany is not a promise that models are infallible, a hidden swarm that bypasses review, or a requirement to buy six AI products. A valid company may have one human plus two AI workers or a larger heterogeneous roster. The operating model is deliberately stronger than any individual model.

It is also not a literal copy of Spotify, Agency Agents, Headroom, or Tabibi. It extracts tested/relevant invariants and makes provenance explicit.

## The design principle

> **Replace clever coordination with explicit contracts that can be checked.**

The strongest model should spend its context solving the product problem, not rediscovering who owns the task, whether the branch is current, whether a review is stale, what the budget permits, or which actor can actually execute.

## Status

The `0.1.0-foundation` baseline is intentionally safe: actors are disabled/unconfigured, readiness is unverified, additional spend defaults to zero, unattended provider workflows are only disabled templates, and autonomy starts low. A deployment becomes autonomous by proving capability and deliberately raising authority — not by copying secrets into a template.

## Contributing

Start with [`CONTRIBUTING.md`](CONTRIBUTING.md), then follow OneCompany itself: bounded Work Unit, single implementation lease, deterministic CI, independent exact-head review, and expected-head merge.
