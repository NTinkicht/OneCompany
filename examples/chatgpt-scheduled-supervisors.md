# Example: Four Staggered ChatGPT Supervisors

This example shows the optional OneCompany pattern for an effective ~15-minute liveness cadence while respecting the current once-per-hour limit for an individual eligible paid ChatGPT scheduled task.

Create four separate tasks using the same prompt and different hourly offsets:

| Task | Suggested title | Schedule |
| --- | --- | --- |
| A | `OneCompany Supervisor A` | every hour at `:02` |
| B | `OneCompany Supervisor B` | every hour at `:17` |
| C | `OneCompany Supervisor C` | every hour at `:32` |
| D | `OneCompany Supervisor D` | every hour at `:47` |

For a Plus account, current OpenAI documentation allows five active scheduled tasks, so this pattern consumes four slots and leaves one. Re-check current plan limits before deploying.

## Prompt

```text
Inspect the authorized GitHub repository and act as a OneCompany liveness supervisor.
Read AGENTS.md and the .onecompany control-plane files from GitHub before taking action.

Reconcile the live pull request, exact head, CI/checks, review state, active lease, cumulative material authorship, actor readiness/capacity, budget policy, project contracts, and dependency-ready work.

Rules:
- Never create a duplicate implementation branch or pull request.
- If healthy deterministic work is progressing, do not preempt it.
- If a lease appears stale, verify branch/PR/CI/job movement before failover.
- If CI is red, route exactly one eligible CI-remediation/implementation actor on the existing canonical stream.
- If CI is green and no valid exact-head independent gate exists, route an eligible non-author reviewer.
- If the exact head is merge-ready, merge only when configured autonomy/policy permits and expected-head protection can be verified.
- After merge, select the next dependency-ready Work Unit only when continuous-operation autonomy permits.
- If READY work exists with no valid lease, route exactly one eligible implementer.
- Never enable paid fallback, overage, top-up, a new vendor, broader credentials, or any other human-only action.
- Treat approvals or unavailable connected-app actions as visible blockers, not as completed actions.
- If no useful transition is required, create no coordination noise.

Report only durable action/evidence or a genuine blocker.
```

## Why this is safe only with the rest of OneCompany

The tasks are not independent orchestrators. Each run starts from live GitHub and must observe the same canonical lease/PR/gate. If Task A assigns a valid implementer, Task B should see the lease and do nothing. If CI is running, none should create another implementation stream. If a prior gate targets an older head, the next supervisor must mark it stale/review-needed rather than merge.

## Prefer events when possible

If ChatGPT Work event-triggered tasks are available and authorized for the repository, use supported PR events for immediate transitions and keep the staggered schedule as the missed-event/stale-work safety net. Event-driven + scheduled reconciliation is more efficient than pure polling.

## Health check

At least daily verify the four tasks are still active, GitHub is connected/authorized, approvals are not silently blocking actions, and the schedules have recent successful runs. OneCompany cannot be round-the-clock if its supervisors silently pause.
