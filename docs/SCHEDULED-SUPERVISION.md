# Scheduled Supervision and 24/7 Company Operation

OneCompany can run around the clock, but a scheduler is a **liveness/reconciliation function**, not an extra implementer.

> **Events move the company; schedules make sure no transition was missed.**

A supervisor reconciles the approved planning baseline, live GitHub state, durable coordination, worker readiness/capacity and budget. It may fill safe WIP slots with dependency-ready conflict-free WUs, but it never creates a duplicate writer for an existing WU.

## Layered 24/7 model

1. **Event-driven handoff** - PR updates, CI completion, reviews and merges should trigger the next bounded transition as quickly as practical.
2. **Scheduled reconciliation** - periodically inspect live GitHub in case an event path failed or a worker went silent.
3. **Portfolio flow check** - recompute dependency readiness, conflict-safe candidates, WIP availability and actor capacity after relevant events.
4. **Scheduler-health check** - verify supervisors remain active and authorized.
5. **Nightly maintenance** - low-priority dependency/security/documentation/control-plane hygiene.
6. **Human escalation** - only for explicit human-only decisions, not routine relaying/scheduling.

This is stronger than “wake every agent every 15 minutes.” More workers do not create more authority. Parallelism is admitted only when the planner proves it safe.

## Supervisor states

`python onecompany.py supervise --force-observe` can emit states such as:

```text
IDLE_NO_READY_WORK
IDLE_READY_WORK_BLOCKED
START_READY_WORK
START_PARALLEL_READY_WORK
ACTIVE_WORK_IN_PROGRESS
RECONCILE_POSSIBLY_STALE_LEASE
CI_REMEDIATION_NEEDED
INDEPENDENT_REVIEW_NEEDED
MERGE_READY
MULTI_ACTION
RECONCILE_CLOSED_PR_AND_SELECT_NEXT
RECONCILE_UNLEASED_PR
RECONCILE_OPEN_PRS
```

A no-idle fault is actionable only when at least one WU is genuinely executable under dependency/conflict/WIP policy **and** an eligible budget-permitted worker has verified implementation capacity.

## GitHub Actions schedule

A disabled template lives at `.onecompany/templates/workflows/onecompany-supervisor.yml.disabled`.

The conservative profile can run hourly away from the top of the hour. Exact cron timing is never a correctness dependency.

A responsive profile may use:

```yaml
schedule:
  - cron: '2,17,32,47 * * * *'
```

That gives an effective ~15-minute reconciliation cadence while avoiding one monolithic poll at `:00`. Runner minutes and provider invocations are budget resources; faster polling is not inherently better.

## Multiple scheduled supervisors

When platform limits require staggered scheduled tasks, treat them as replicas of **one** supervisory function. Every run starts by re-reading authoritative state; none owns implementation merely because it woke up first.

Important constraints:

- authoritative OneCompany contracts live in GitHub, not in chat memory;
- scheduled runs must reconcile current PR head **and base** SHAs before consequential transitions;
- connected-app actions may require approval; approval waits are visible blockers, not assumed success;
- a supervisor must not infer capacity from a worker simply being configured — readiness and capacity must be verified;
- event-triggered transitions are preferable where reliable; scheduled reconciliation remains the missed-event safety net;
- supervisors must remain budget-compliant and may not enable paid fallback, overage, top-up or new vendors.

## Recommended supervisor prompt

```text
Inspect the authorized GitHub repository as a OneCompany liveness supervisor.
Use the trusted base AGENTS.md/company constitution and the current approved .onecompany baseline.

1. Reconcile approved WU/requirement/risk state with live PRs, exact head/base SHAs, changed files, CI/checks, review/gate state, active leases, material authorship, worker readiness/capacity and budget policy.
2. Never create a competing implementation branch/PR/lease for an already-owned Work Unit.
3. Recompute dependency-ready work and the conflict-safe parallel set. Respect global WIP, declared scopes, semantic resource locks, risk policy and per-actor implementation capacity.
4. If healthy deterministic work is progressing on a WU, do not preempt that WU.
5. If a lease appears stale, verify branch/PR/CI/job movement before failover. Failover changes the worker, not the canonical WU stream.
6. If CI is red, route one eligible remediation/implementation worker for that existing WU stream.
7. If CI is green and no valid independent exact-head/base gate exists, route an eligible non-author reviewer.
8. If a gate is merge-ready, confirm live scope still matches the WU, required checks are green, head/base SHAs still match, governance permits merge, and expected-head protection is available.
9. After a merge, release only that WU stream, recompute the portfolio graph, and start newly unlocked WUs only within safe WIP/capacity.
10. READY work is not automatically executable. If all READY work is dependency/conflict/WIP/capacity blocked, report the real blocker rather than FAULT_IDLE.
11. Never enable paid fallback, overage, top-up, new credentials, new vendors, risk acceptance, or another human-only action.
12. If no useful transition is required, create no coordination noise.

Report durable action/evidence or a genuine blocker only.
```

## Why multiple supervisors are not multiple orchestrators

They converge on the same authoritative model:

- existing canonical lease for WU-A → no duplicate writer for WU-A;
- WU-B independently safe + WIP slot + worker capacity → WU-B may start;
- WU-C conflicts with WU-A → hold WU-C;
- CI running → do not duplicate remediation;
- current exact-head/base gate already exists → no redundant review;
- head moved → gate stale;
- base moved after another merge → integration evidence stale;
- no dependency-ready executable work → legitimate idle/blocking state.

## Monitor the monitors

At least daily, verify:

- external scheduled tasks still exist and are enabled;
- GitHub scheduled workflows have recent runs;
- connected-app authorization still works;
- unattended provider entitlements remain valid without printing secrets;
- scheduler failures are visible in the Team Room/notifications;
- no scheduler silently acquired broader permissions or a different billing path;
- liveness decisions remain consistent with actual WIP/worker capacity.

Supervisor failure should become a visible operational state; otherwise a company can appear autonomous while its liveness layer has silently died.

## Capacity recovery

Do not hammer quota-limited workers/providers on every pass. Record capability-specific degradation and re-probe only when a reasonable reset window or new evidence exists. A recovered preferred worker does not preempt a healthy replacement mid-attempt.

## Nightly / daily maintenance lane

Keep low-priority maintenance separate from delivery supervision. It may inspect dependency/security advisories, documentation/control-plane drift, failed schedules, queue/traceability drift, provider version pins, unresolved retrospectives, technical debt and credential-expiry warnings. Maintenance does not interrupt healthy critical work without a safety reason.

## Cost model

Prefer:

```text
event trigger             -> immediate bounded transition
portfolio reconciliation  -> fill safe WIP / catch stale state
scheduled reconciliation  -> missed-event safety net
nightly maintenance       -> low-priority hygiene
```

“24/7” means continuous recoverability and flow, not infinite polling.

## Stop switch

1. set emergency stop when containment is required;
2. pause/delete external scheduled tasks;
3. disable event-triggered tasks;
4. disable the OneCompany supervisor workflow;
5. set `supervision.enabled=false`;
6. lower autonomy/continuous-operation settings;
7. revoke unattended write credentials if required;
8. reconcile all active WU streams before resuming autonomy.
