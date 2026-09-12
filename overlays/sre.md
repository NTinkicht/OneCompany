# Overlay: Site Reliability / Production Readiness

## Lens

Evaluate whether the change behaves safely under failure, load, degraded dependencies, rollout, and recovery.

## Ask

- What is the failure domain and blast radius?
- Are timeout/retry/backoff/idempotency semantics bounded?
- What signal proves healthy behavior?
- How is partial rollout or provider degradation handled?
- Is there a rollback/recovery path?
- Are alerts/logs useful without leaking sensitive data?

## Expected artifact

Production-readiness checklist, failure matrix, observability requirements, and recovery/rollback evidence.
