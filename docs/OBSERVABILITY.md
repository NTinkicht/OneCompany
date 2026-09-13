# Company Observability

Measure the company, not model chatter.

## Core delivery metrics

Useful metrics per WU:

- lead time: READY → MERGED;
- implementation time;
- CI remediation cycles;
- review cycles;
- failover count and reason;
- stale-gate incidents prevented;
- duplicate-stream incidents;
- human-decision wait time;
- rollback/revert rate;
- escaped defect/security incident count.

## Capacity metrics

- actor availability by capability;
- quota-limit events;
- fallback success rate;
- time blocked with no eligible route;
- included/free/local vs metered usage class.

Do not invent precise token/cost numbers when a subscription does not expose reliable usage data.

## Governance metrics

- merges without exact-head gate (should be zero when required);
- self-review conflicts prevented;
- budget-policy violations (zero target);
- secrets/sensitive logging incidents (zero target);
- `FAULT_IDLE_WITH_READY_WORK` duration;
- state drift detections.

## Privacy

Prefer categorical and aggregate observability. Company telemetry should not need source payloads, credentials, customer contact data, clinical data, or full prompt transcripts.

## Anti-metric

Do not optimize “messages sent by agents,” “number of agents active,” or raw commit count. They reward churn and duplication rather than delivered value and risk closure.
