# Scheduled Supervision and 24/7 Company Operation

OneCompany can run around the clock, but the scheduler must not become a second implementation stream.

> **Events move the company; schedules make sure no transition was missed.**

A scheduled task is a liveness supervisor. It reconciles live GitHub state, detects a missing handoff, stale lease, green CI waiting for review, merge-ready head, or ready work with no lease. It should not blindly start coding while another canonical stream is healthy.

## Layered 24/7 model

1. **Event-driven handoff** - PR updates, CI completion, reviews and merges should trigger the next bounded transition as quickly as practical.
2. **Scheduled reconciliation** - periodically inspect live GitHub in case an event path failed or an actor went silent.
3. **Scheduler-health check** - verify that the supervisors themselves are still active and able to access GitHub.
4. **Human escalation** - only for explicit human-only decisions, not routine relaying/scheduling.

This is stronger than “wake every agent every 15 minutes.” Multiple writers create races; OneCompany routes only the capability needed for the next state transition.

## Supervisor states

`python onecompany.py supervise --force-observe` can emit states such as:

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

## GitHub Actions schedule

A disabled template lives at `.onecompany/templates/workflows/onecompany-supervisor.yml.disabled`.

The conservative profile runs hourly at minute 17. GitHub documents that scheduled runs can be delayed during high load, especially around the top of the hour, so exact cron timing must never be a correctness dependency. GitHub scheduled workflows also run from the default branch; the enabled workflow must therefore exist there.

A responsive profile can use:

```yaml
schedule:
  - cron: '2,17,32,47 * * * *'
```

That gives an effective ~15-minute check. GitHub supports schedules as frequent as every five minutes, but OneCompany discourages aggressive polling because Actions minutes and provider invocations are budget resources.

## Four staggered ChatGPT scheduled supervisors

Eligible paid ChatGPT plans currently support recurring scheduled tasks up to once per hour. A 15-minute **effective** supervisory cadence can therefore use four hourly tasks staggered across the hour:

| Supervisor | Run minute |
| --- | ---: |
| A | :02 |
| B | :17 |
| C | :32 |
| D | :47 |

For ChatGPT Plus, the current active-task limit is five, so this leaves one active-task slot. Product limits can change; re-check current OpenAI documentation before deploying the pattern elsewhere.

### Important ChatGPT task constraints

- The supervisor must read live GitHub through a connected/authorized GitHub app; it must not rely on old conversation state.
- A scheduled task created in a ChatGPT Project must **not** assume it can access files uploaded/stored in that Project. Keep authoritative OneCompany contracts in GitHub.
- Connected-app actions may require approval; if an action pauses for approval, the company must treat that as a visible blocker rather than assume mutation happened.
- Scheduled tasks can pause or become inactive. Check supervisor health daily and keep an event/schedule fallback.
- Event-triggered Work tasks can react to supported GitHub pull-request activity and are preferable to polling where available; scheduled reconciliation remains the missed-event safety net.

### Recommended supervisor prompt

```text
Inspect the authorized GitHub repository and act as a OneCompany liveness supervisor.
Read AGENTS.md and the .onecompany control-plane files from GitHub before taking action.

1. Reconcile live PR, exact head, CI/checks, review state, active lease, material authorship, actor readiness/capacity, budget policy, and dependency-ready work.
2. Never create a duplicate implementation branch or PR.
3. If healthy deterministic work is progressing, do not preempt it.
4. If a lease appears stale, verify branch/PR/CI/job movement before failover.
5. If CI is red, route exactly one eligible CI-remediation/implementation actor on the existing canonical stream.
6. If CI is green and no valid exact-head independent gate exists, route an eligible non-author reviewer.
7. If the exact head is merge-ready, merge only when autonomy/policy permits and expected-head protection can be verified.
8. After merge, select the next dependency-ready Work Unit only when continuous-operation autonomy permits.
9. If ready work exists with no valid lease, route exactly one eligible implementer.
10. Never enable paid fallback, overage, top-up, a new vendor, broader credentials, or another human-only action.
11. If no useful transition is required, create no coordination noise.

Report only durable action/evidence or a genuine blocker.
```

## Why four supervisors are not four orchestrators

They are replicas of one liveness function. Every run begins from live GitHub state:

- existing lease → no duplicate implementation;
- CI running → do not create another writer;
- current exact-head review already requested → no redundant generic review;
- new head after approval → gate is stale and must be refreshed;
- no READY work → legitimate idle.

## Monitor the monitors

At least daily, verify:

- external scheduled tasks still exist and are enabled;
- GitHub scheduled workflows are enabled and have recent runs;
- GitHub connected-app authorization still works;
- unattended provider credentials/entitlements remain valid without printing secrets;
- scheduler failures are visible in Team Room/notifications;
- no scheduler has silently acquired broader permissions or a different billing path.

Supervisor failure should become a visible operational state; otherwise a company can look “autonomous” while its liveness layer has silently died.

## Capacity recovery

Do not hammer quota-limited providers on every 15-minute pass. Record capability-specific degradation and re-probe only when a reasonable reset window/new evidence exists. A recovered preferred actor does not preempt a healthy replacement mid-attempt.

## Nightly / daily maintenance lane

Keep low-priority maintenance separate from delivery supervision. A daily task may inspect dependency/security advisories, documentation/control-plane drift, failed schedules, queue dependency drift, provider version pins, unresolved retrospectives and credential-expiry warnings. Maintenance must not interrupt healthy critical work without a real safety reason.

## Cost model

Prefer:

```text
event trigger -> immediate bounded transition
scheduled reconciliation -> stale/missed-event safety net
nightly maintenance -> low-priority hygiene
```

If a schedule causes billable runner/provider usage, lower the cadence or use included alternatives. “24/7” means continuous recoverability, not infinite polling.

## Stop switch

1. pause/delete external scheduled tasks;
2. disable event-triggered tasks;
3. disable the OneCompany supervisor workflow;
4. set `supervision.enabled=false`;
5. set continuous queue false and/or lower autonomy;
6. revoke unattended write credentials if containment is required.
