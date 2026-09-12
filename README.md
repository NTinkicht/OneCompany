# OneCompany

**One human. A team of AI workers. One autonomous company.**

OneCompany is an open operating system for running software projects as autonomous, multi-agent companies from GitHub. It turns a repository into a governed organization: work is decomposed into bounded units, routed by capability, leased to one implementer, verified by deterministic CI, independently reviewed on the exact commit, merged, reconciled, and followed immediately by the next dependency-ready unit of work.

OneCompany was designed from real operating experience building Tabibi with ChatGPT, Codex, Claude, GitHub Copilot, Gemini CLI, Mistral Vibe, GitHub Actions, and strict zero-extra-spend constraints. It is intentionally provider-neutral: **roles belong to the company, not to model brands.**

## The promise

OneCompany gives a project a reusable control plane for:

- multi-agent orchestration without duplicate implementation streams;
- capability-based routing and explicit work leases;
- automatic failover when an actor is unavailable, quota-limited, or unsuitable;
- independent non-author review and exact-head merge gates;
- deterministic CI as the technical referee;
- machine-readable company state, queue, actors, roles, policies, and budgets;
- no-idle detection when ready work exists but nobody holds a valid lease;
- cost and capacity governance, including a hard zero-extra-spend mode;
- privacy, secret, permissions, logging, and untrusted-input boundaries;
- human override points for decisions that should never be silently automated;
- migration into existing repositories without rewriting the product;
- simulation and self-tests for the company itself.

## Core loop

```text
Observe repository reality
        ↓
Reconcile declared state with GitHub
        ↓
Select smallest dependency-ready Work Unit
        ↓
Route required capabilities
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

## Quick start

1. Read [`BOOTSTRAP.md`](BOOTSTRAP.md).
2. Copy `.onecompany/` and the recommended GitHub templates/workflows into your project.
3. Edit `.onecompany/config.json` with your project, budget, CI contract, actors, and autonomy level.
4. Register available workers in `.onecompany/actors.json`.
5. Run:

```bash
python scripts/doctor.py
python scripts/validate.py
```

6. Create your first Work Unit from `.github/ISSUE_TEMPLATE/work-unit.md`.
7. Assign a single implementation lease.
8. Let CI and a non-author reviewer gate the exact head before merge.

For an existing repository, start with [`docs/MIGRATION.md`](docs/MIGRATION.md).

## Autonomy levels

| Level | Name | What OneCompany may do |
|---|---|---|
| L0 | Manual | Documentation/state only; humans execute all work. |
| L1 | Assisted | AI proposes plans and patches; humans authorize execution. |
| L2 | Autonomous Implementation | AI may implement bounded Work Units; humans gate merge. |
| L3 | Autonomous Delivery | Implementation, CI remediation, independent review, and merge can run autonomously inside policy. |
| L4 | Continuous Company | The company selects the next ready Work Unit and continues without idle gaps. |
| L5 | Governed Autonomous Company | Product delivery, maintenance, incident response, capacity failover, state reconciliation, and planning all run continuously, with explicit human-only decision classes. |

See [`docs/AUTONOMY-LEVELS.md`](docs/AUTONOMY-LEVELS.md).

## Non-negotiable invariants

1. **GitHub is the operational source of truth.** Chat, Slack, memory, dashboards, and local notes are mirrors or attention layers.
2. **One Work Unit has one canonical implementation stream.** Do not solve the same bounded task on competing branches unless a human explicitly authorizes an experiment.
3. **A lease is explicit.** Nobody should infer ownership from activity alone.
4. **Failover keeps the stream.** If the worker changes, the branch, PR, objective, and acceptance contract remain the same.
5. **The author cannot be the sole independent gate.**
6. **Reviews target an exact SHA.** A verdict on an older head is stale after any commit.
7. **Green CI is necessary, not sufficient.** Independent review is necessary for configured risk classes.
8. **Merge uses expected-head protection.** Never merge a commit different from the gated commit by accident.
9. **Ready work + no valid lease = operational fault.**
10. **Budgets are policy.** No agent may silently enable paid fallback, overage, credits, auto-top-up, or a new vendor.
11. **Secrets and sensitive data stay out of prompts, logs, state files, issue bodies, and PR comments.**
12. **Humans keep authority over irreversible, regulated, financial, credential, production-destructive, and policy-changing decisions unless explicitly delegated.

## Repository map

```text
.onecompany/                 Machine-readable company control plane
  config.json                Project and autonomy configuration
  actors.json                Worker registry and capabilities
  roles.json                 Role contracts and routing preferences
  state.json                 Reconciled operational snapshot
  queue.json                 Work Unit dependency queue
  budget.json                Spend/capacity policy
  schemas/                   JSON Schemas for control-plane files
agents/                      Worker-specific onboarding guides
company/                     Constitution and operating procedures
docs/                        Architecture, security, migration, runbooks
scripts/                     Dependency-light validation and diagnostics
.github/                     PR/issue templates and safe workflows
examples/                    Reference company/project examples
starter/                     Files intended to be copied into another repo
```

## What OneCompany is not

OneCompany is not a promise that models are infallible, a hidden swarm that bypasses review, or a requirement to buy six AI products. A valid company may have one human plus two AI workers, or a larger heterogeneous roster. The operating model is deliberately stronger than any individual model.

## The design principle

> **Replace clever coordination with explicit contracts that can be checked.**

The strongest model should spend its context solving the product problem, not rediscovering who owns the task, whether the branch is current, whether a review is stale, what the budget permits, or which actor is allowed to merge.

## Status

OneCompany is being built as a reusable reference implementation and operating specification. The control plane is designed to remain useful even when specific AI vendors, subscription plans, interfaces, or models change.

## Contributing

Start with [`CONTRIBUTING.md`](CONTRIBUTING.md), then follow OneCompany itself: bounded Work Unit, single implementation lease, CI, independent exact-head review, and expected-head merge.
