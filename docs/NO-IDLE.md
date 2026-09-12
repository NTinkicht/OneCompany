# No-Idle Operation

OneCompany's no-idle principle is **not** “keep every AI busy.” It is “do not leave dependency-ready valuable work unowned when policy permits execution.”

## Healthy waiting

These are not idle failures:

- CI is actively running;
- an independent reviewer is actively executing;
- required human decision is pending;
- no dependency-ready work exists;
- all eligible workers are capacity-blocked under budget policy;
- a deliberate cooldown/rate-limit window is recorded.

## Fault condition

The canonical fault is:

```text
READY_WORK_EXISTS
AND no valid implementation lease
AND autonomy permits continuation
AND at least one eligible route exists
→ FAULT_IDLE_WITH_READY_WORK
```

## Durable heartbeat

Do not use “agent said it started” as heartbeat. Use durable evidence such as:

- new commit on leased branch;
- PR creation/update;
- Actions run started/completed;
- exact-head review posted;
- issue/state transition;
- reproducible diagnostic artifact.

## Failover vs patience

Fail over when evidence indicates the current worker cannot progress: explicit quota, permission/tool failure, repeated identical unsuccessful remediation, timeout with no durable artifact, or human override.

Do not fail over merely because a long test suite/review is legitimately running.

## Frequency

High-frequency polling can cost money and create noise. Prefer event-driven triggers. If scheduled monitoring is needed, choose the slowest cadence compatible with the failure you are trying to detect and your runner budget. OneCompany ships its watchdog disabled by default for this reason.

## Utilization principle

A specialist with nothing useful to do may remain idle. Creating dummy production changes to increase “agent utilization” is an anti-pattern. Safe diagnostic/dummy tasks are useful only to validate a newly configured worker/runtime.
