# Configuration Reference

The reference control plane lives in `.onecompany/`. JSON keeps validation/automation dependency-light.

## `config.json`

`project` identifies the target GitHub repository/default branch. `autonomy` chooses L0-L5. `delivery` enables single-stream leases, exact-head review, independent non-author gating and expected-head merge. `coordination` keeps GitHub authoritative. `no_idle` governs continuous-company liveness. `human_only_decisions` records actions automation may not silently take.

## `budget.json`

Defines additional AI spend cap, paid fallback/overage/top-up/new-vendor rules, CI-runner policy and actor cost classes. Unknown cost should normally fail closed. A valid provider key is not proof that its invocation is financially allowed.

## `actors.json` - potential capability

Declares stable actor identity, possible execution modes, cost class, permissions summary and potential capabilities. It is not proof that today's account/runtime can perform them.

## `readiness.json` - proven current route

Records setup state, verified surfaces/capabilities, capability-specific temporary degradation, proved repository read/write/review/merge access, unattended readiness and non-secret smoke evidence.

This distinction lets OneCompany represent states such as “implementation works; review quota is exhausted.”

## `routing.json`

Capability-specific preference order **after** hard eligibility filters. Live readiness, budget, permissions and reviewer independence outrank preference. A preference is never a lease and a recovered preferred actor does not preempt a healthy replacement mid-attempt.

## `roles.json`

Defines orchestrator, implementer, scout, test/failure roles, independent/security review, CI remediation and merge execution contracts. Roles belong to the company, not permanently to providers.

## `supervision.json`

Controls round-the-clock liveness supervision.

Key areas:

- `enabled` / `mode`: disabled/observe/notify/orchestrate posture;
- `continuous_operation`: event-first, scheduled reconciliation, stale-candidate threshold and effective cadence;
- `github_actions`: optional scheduled supervisor profile;
- `chatgpt_tasks`: optional staggered external supervisor profile;
- `scheduler_health`: daily health, visible failure, no exact-cron dependency, no assumption that ChatGPT Project files are available;
- `coordination.team_room_issue_number`: optional durable reporting target;
- `safety`: scheduler-not-implementer, live-reconcile-before-action, no duplicate streams, no budget/human-boundary override, autonomy floors for auto-merge/next-work.

The safe template starts `enabled=false`, `mode=observe_only`, with no failover/merge/mutation authority.

## `queue.json`

Dependency index for bounded WUs. A fresh bootstrap resets it to empty so OneCompany's own history cannot leak into a new project. `python onecompany.py next-work` derives candidates whose dependencies are `MERGED/DONE` and suppresses starting another stream while canonical work is active.

## `state.json`

Operational cache: current WU/PR/head, cumulative material authors, active leases, exact-head gate, ready count, blockers and human-decision flag. Live GitHub wins on conflict.

## `patterns.json` and `overlays.json`

Patterns document the operating techniques/invariants. Overlays provide bounded professional lenses. An overlay cannot create an actor, capacity, lease, permission, reviewer independence or merge authority.

## Project foundation contracts

The control plane is not a substitute for product truth. Recommended root contracts are:

```text
PRODUCT.md
ARCHITECTURE.md
SECURITY.md
QUALITY.md
OPERATIONS.md
```

Templates are under `.onecompany/templates/contracts/`. See `docs/PROJECT-CONTRACTS.md`.

## Schemas and cross-file validation

Schemas live under `.onecompany/schemas/`. `python onecompany.py validate` also runs cross-file checks ordinary JSON Schema cannot prove: actor↔readiness coherence, role capability coverage, routing references, budget contradictions, single-stream leases, exact-head/authorship consistency and supervision safety.

## Adding project-specific fields

Schemas allow bounded extension where appropriate. Update validation when an extension affects safety, routing, spending or authority. Never hide a new paid path or permission expansion inside an opaque custom field.
