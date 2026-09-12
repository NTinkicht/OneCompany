# Incident Runbook

Use this for autonomy, security, cost, or coordination incidents.

## 1. Contain

Depending on severity:

- disable/revoke unattended write credentials;
- disable auto-merge;
- lower autonomy to L0/L1;
- stop scheduled workflows/runners;
- freeze deployment or affected branch;
- rotate exposed credentials;
- preserve logs/evidence without copying secrets into issues.

Contain first; optimize throughput later.

## 2. Establish repository truth

Record:

- default branch SHA;
- affected branch/PR heads;
- recent merges;
- active workflow runs;
- active leases;
- actor(s) involved;
- policy version in effect;
- whether any review/merge gate was stale or bypassed.

Do not rely on chat summaries alone.

## 3. Classify

Suggested classes:

- `SECURITY`
- `CREDENTIAL`
- `BUDGET`
- `DUPLICATE_IMPLEMENTATION`
- `STALE_GATE`
- `STATE_DRIFT`
- `BAD_MERGE`
- `PROMPT_INJECTION`
- `PROVIDER_OUTAGE`
- `AUTONOMY_POLICY`

## 4. Recover

Use the smallest reversible path. Prefer revert/new fix PR over rewriting shared history. Re-run deterministic verification and independent review after recovery changes.

## 5. Learn

Convert root cause into one or more of:

- validation invariant;
- simulation drill;
- permission reduction;
- workflow guard;
- clearer WU template;
- router/failover rule;
- documentation/runbook update.

A recurring incident should become impossible or at least mechanically detectable.

## 6. Restore autonomy gradually

Re-enable write/merge/schedules only after the violated invariant is repaired and the relevant simulation passes.
