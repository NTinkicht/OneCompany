# Scheduled Supervision and 24/7 Company Operation

OneCompany can run around the clock, but the scheduler must not become a second implementation stream.

The core principle is:

> **Events move the company; schedules make sure no transition was missed.**

A scheduled task is a liveness supervisor. It reconciles live GitHub state, detects a missing handoff, stale lease, green CI waiting for review, merge-ready head, or ready work with no lease. It should not blindly start new coding while another canonical stream is healthy.

## Layered 24/7 model

Use three layers:

1. **Event-driven handoff** - PR updates, CI completion, review verdicts, issue comments and merges should trigger the next bounded transition as quickly as practical.
2. **Scheduled reconciliation** - periodically inspect the live repository in case an event path failed, an actor went silent, or a lease became stale.
3. **Human escalation** - only for explicit human-only decisions, not routine scheduling or message relaying.

This is stronger than “wake every agent every 15 minutes.” Waking multiple writers produces races. OneCompany wakes or routes only the capability needed for the next state transition.

## The supervision state machine

A supervisor should distinguish at least:

```text
IDLE_NO_READY_WORK
START_READY_WORK
ACTIVE_WORK_IN_PROGRESS
RECONCILE_POSSIBLY_STALE_LEASE
CI_REMEDIATION_NEEDED
INDEPENDENT_REVIEW_NEEDED
MERGE_READY
RECONCILE_CLOSED_PR_AND_SELECT_NEXT
RECONCILE_UNLEASED_PR
RECONCILE_OPEN_PRS
```

`python onecompany.py supervise --force-observe` produces a read-only recommendation from live GitHub evidence.

## GitHub Actions schedule

OneCompany ships a disabled template at:

`.onecompany/templates/workflows/onecompany-supervisor.yml.disabled`

The conservative profile runs once per hour at minute 17 rather than the top of the hour. GitHub notes that scheduled workflows can be delayed at high-load times, especially near the start of the hour, so exact timing must not be a correctness dependency.

A more responsive profile can use:

```yaml
schedule:
  - cron: '2,17,32,47 * * * *'
```

That is an effective 15-minute reconciliation cadence. Use it only after checking Actions usage/cost policy. Scheduled GitHub Actions are not free in every repository/plan context, so frequency is a budget decision.

The shortest supported GitHub Actions schedule interval is currently five minutes, but OneCompany strongly discourages using five-minute polling unless the project genuinely needs it.

## Four staggered ChatGPT scheduled supervisors

Eligible paid ChatGPT plans currently support recurring scheduled tasks up to once per hour. A useful pattern for a 15-minute **effective** supervisory cadence is therefore four hourly tasks staggered across the hour:

| Supervisor | Run minute every hour |
| --- | ---: |
| A | :02 |
| B | :17 |
| C | :32 |
| D | :47 |

Each task runs only once per hour; together they provide a check approximately every 15 minutes. Do not schedule all four at the same minute.

For ChatGPT Plus, the current active-task limit is five, so a four-supervisor mesh intentionally leaves one slot available for another task. Re-check current OpenAI limits before relying on this profile because product limits can change.

### Recommended supervisor prompt

Use the same operating contract for all four tasks; only the schedule differs:

```text
Inspect the authorized GitHub repository and act as a OneCompany liveness supervisor.
Read AGENTS.md and the .onecompany control-plane files before taking action.

1. Reconcile live PR, exact head, CI/checks, review state, active lease, material authorship, actor readiness/capacity, budget policy, and READY work.
2. Never create a duplicate implementation branch or PR.
3. If healthy deterministic work is progressing, do not preempt it.
4. If a lease appears stale, verify branch/PR/CI/job movement before failover.
5. If CI is red, route exactly one eligible CI-remediation/implementation actor on the existing canonical stream.
6. If CI is green and no valid exact-head independent gate exists, route an eligible non-author reviewer.
7. If the exact head is merge-ready, merge only when OneCompany autonomy/policy permits and expected-head protection can be verified.
8. After a completed merge, reconcile and select the next dependency-ready Work Unit only when continuous-operation autonomy permits.
9. If ready work exists with no valid lease, route exactly one eligible implementer.
10. Never enable paid fallback, overage, top-up, a new vendor, broader credentials, or another human-only action.
11. If no useful transition is required, produce no coordination noise.

Report only durable action/evidence or a genuine blocker.
```

Scheduled tasks must have access to the required GitHub connected app/permissions. A task that cannot inspect live GitHub is not a valid OneCompany supervisor.

## Event-triggered ChatGPT Work tasks

Where available, GitHub event-triggered Work tasks are preferable to polling for supported pull-request activity. They can react sooner and reduce idle polling. Use scheduled reconciliation as the safety net even when event triggers exist.

An event-triggered task must still obey the same lease, budget, authorship, exact-head and human-only boundaries. Connected-app authorization does not create extra company authority.

## Why four supervisors are not four orchestrators

The four scheduled tasks are replicas of the **same supervisory function**, not four independent decision makers. Every run begins by reading live GitHub state. Durable leases and exact-head state make concurrent/repeated checks idempotent:

- if another supervisor already routed an implementer, the next supervisor observes the lease and does nothing;
- if CI is still running, the next supervisor does not start another implementation;
- if a review already targets the current SHA, the next supervisor does not request a duplicate generic review;
- if the head changed after approval, the next supervisor sees the stale gate and requests re-gating;
- if there is no READY work, legitimate idle is allowed.

## Capacity recovery checks

Do not hammer a quota-limited provider every 15 minutes. Record capability-specific degradation in `readiness.json` and re-probe only when a reasonable reset window or new evidence justifies it. A recovered preferred actor does not preempt a healthy replacement mid-attempt.

## Nightly / daily maintenance lane

Continuous delivery supervision should be separate from maintenance. A daily or nightly low-priority task may check:

- dependency/security advisories;
- stale docs/control-plane drift;
- failing scheduled workflows;
- queue dependency drift;
- repository hygiene;
- unresolved retrospectives/process proposals;
- expiring credentials or known integration changes;
- provider/CLI version pins that need a reviewed upgrade.

Maintenance must not interrupt a healthy critical delivery stream without a real BLOCKER/security reason.

## Cost model

Round-the-clock does not mean infinite polling.

Prefer:

```text
event trigger -> immediate bounded transition
scheduled reconciliation -> missed-event/stale-work safety net
nightly maintenance -> low-priority hygiene
```

For zero-extra-spend projects, scheduled tasks and Actions runner usage are part of the budget. If a schedule would create billable runner/provider usage, lower the cadence or use already-included alternatives.

## Failure behavior

A supervisor that cannot authenticate, inspect GitHub, or confirm cost eligibility should report `CAPACITY_DEGRADED` and stop. It must never compensate by enabling a paid API path or guessing repository state from old chat context.

## Stop switch

To stop 24/7 operation quickly:

1. pause/delete external scheduled tasks;
2. disable event-triggered tasks;
3. disable the OneCompany supervisor workflow;
4. set `supervision.enabled=false`;
5. set `autonomy.continue_when_ready_work_exists=false` and/or lower autonomy;
6. revoke unattended write credentials if containment is required.

The company should stop cleanly without deleting its durable GitHub history.
