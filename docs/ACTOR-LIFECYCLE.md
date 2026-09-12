# Actor Lifecycle: Add, Degrade, Recover, Rotate, Retire

A reusable autonomous company must manage workers over time, not only onboard them once.

## Add

1. Add the actor to `actors.json` with potential capabilities and cost class.
2. Add a matching `readiness.json` record in `not_started` state.
3. Configure one execution surface at a time.
4. Smoke-test read/write/review/merge capabilities separately.
5. Record non-secret evidence.
6. Add the actor to relevant `routing.json` preference lists only where it actually has the declared capability.
7. Enable only after the intended route is ready.

## Degrade

Quota, outage, auth or runtime failure should affect the smallest capability possible.

Example:

```text
actor: codex
implementation: available
code_review: temporarily unavailable
```

Do not disable an entire actor when only one capability is degraded.

## Recover

Re-probe only when a reset window or new evidence justifies it. Record `CAPACITY_RECOVERED`, clear only the affected degradation, and do not preempt a healthy replacement mid-attempt.

## Credential rotation

Treat new/rotated credentials as a human-governed permission change unless policy explicitly delegates it. Re-run relevant smoke tests after rotation and update readiness evidence; never record the credential itself.

## Retire

1. release/fail over active leases first;
2. remove/disable unattended triggers;
3. revoke credentials and GitHub permissions;
4. set actor `enabled=false`, `configured=false`, readiness `unavailable` or archive according to project policy;
5. remove the actor from new routing preference lists;
6. preserve historical authorship/review records rather than rewriting history.

## Provider/model changes

A new model version or tool surface is not automatically the same readiness. If behavior, permissions, billing path or tool access changed materially, treat it as a new surface and re-smoke the affected capabilities.
