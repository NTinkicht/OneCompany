# Autonomy Levels

Autonomy is a permission boundary. Choose the lowest level that meets the project need and raise it only after evidence.

## L0 — Manual

OneCompany documents roles/state/contracts. Humans execute implementation, review, and merge.

Use for: initial evaluation, regulated environments awaiting approval.

## L1 — Assisted

AI may analyze, plan, draft WUs, propose patches/reviews. Humans explicitly authorize consequential actions.

Use for: learning the operating model without write automation.

## L2 — Autonomous Implementation

AI may accept a bounded implementation lease, push commits, open/update PRs, and remediate deterministic failures. Human remains merge authority by default.

Required maturity: reliable CI, lease discipline, permissions scoped.

## L3 — Autonomous Delivery

Eligible AI workers may implement, run/remediate CI, obtain independent exact-head review, and merge when all policy gates pass. Human decisions remain required for configured risk classes.

Required maturity: exact-head gate enforcement, non-author review, expected-head merge, budget controls.

## L4 — Continuous Company

After a WU completes, the orchestrator reconciles state and selects the next dependency-ready WU automatically. No-idle detection/failover is active.

Required maturity: queue quality, dependency modeling, stable routing/failover, incident stop.

## L5 — Governed Autonomous Company

The company continuously performs delivery, maintenance, regression response, bounded technical planning, capacity failover, state reconciliation, and operational hygiene inside explicit policy. Humans focus on vision, risk appetite, credentials, financial/governance decisions, and exceptional product decisions.

L5 does not mean “no humans.” It means routine execution no longer depends on continuous human prompting.

## Mechanically enforced dispatch floors

The dispatch resolver checks the **installed project's** current autonomy
policy before exposing an unattended mutating capability. Unattended
implementation and deterministic CI remediation require approved L2;
unattended merge requires approved L3; automatically selecting a subsequent WU
requires approved L4 **and** an explicit continuous-selection switch. Read-only
unattended repository intelligence can operate at L1 if its independent
readiness, scope, budget and execution mechanism are verified.

These are minimum authorization floors, **not readiness evidence**. A level
alone does not grant access to a worker, repository, lease, token, protected
branch, paid quota, database, release or merge. The default OneCompany source
and new installations remain L1; this code does not activate or upgrade any
project. Raising the level remains a human-only policy decision.

## Raising the level

Before each increase, run `docs/SIMULATION.md` scenarios and confirm:

- failure does not create duplicate streams;
- reviewer independence is enforced;
- stale SHA cannot merge as approved;
- budget limits survive quota exhaustion;
- secrets remain protected;
- stop/override works;
- state reconciliation repairs drift.

## Lowering the level

A human may lower autonomy immediately. The system should release/stop unattended write leases as appropriate and preserve current repository state for safe continuation.
