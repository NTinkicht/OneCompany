# Unattended Automation

Unattended execution increases both leverage and blast radius. OneCompany therefore treats it as a separately verified capability, not a consequence of interactive login.

## Default posture

- Disabled until deliberately enabled.
- Read-only first.
- Trusted trigger only.
- Minimum tool/permission allow-list.
- Hard runtime/turn/token limits.
- No implicit paid fallback.
- Redacted logs/output.
- Explicit stop/revoke path.
- Non-gating unless a dedicated exact-head review flow proves all normal gate requirements.

## Required preflight

Before invoking a provider:

1. Confirm the actor is enabled/configured for this surface.
2. Confirm the requested capability is currently verified and not temporarily unavailable.
3. Confirm budget/cost class.
4. Confirm credentials exist without printing them.
5. Confirm trigger actor/source is authorized.
6. Confirm repository/WU/branch/PR scope.
7. Apply tool/permission restrictions.
8. Set timeout and output limits.

Failure becomes `CAPACITY_DEGRADED`/`BLOCKED` as appropriate. It does not unlock a paid provider.

## Logging

Live logs should favor lifecycle events:

```text
actor started
tool type/name (when safe)
status
elapsed time
exit class
output size/token count
```

Avoid prompts, tool parameters/results, raw provider stderr, environment variables, credentials, or sensitive payloads. Scrub final model-authored text before publishing it to an issue/PR.

## Generic read-only wake

A read-only wake may inspect repository evidence and return a bounded artifact such as an impact map, failure matrix, or regression scout. It should not edit files, create branches/PRs, change labels, submit binding reviews, or merge unless a separate reviewed automation grants that authority.

## Write-capable automation

Raise authority in stages:

```text
read-only scout
 -> test-only writer
 -> bounded implementation writer
 -> exact-head reviewer (non-author only)
 -> mechanical merge executor
```

Each stage requires its own smoke evidence in `.onecompany/readiness.json`.

## Scheduled checks

Do not schedule a heartbeat merely to keep agents busy. A scheduled watchdog should reconcile state/ready work and act only when useful. Private repository Actions minutes and provider allowances are budget resources.

## Stop mechanism

At minimum, know how to:

- disable the workflow/automation;
- revoke the provider credential;
- disable repository write/merge access;
- set actor `enabled=false` or readiness unavailable;
- reduce autonomy level.

Containment outranks throughput.
