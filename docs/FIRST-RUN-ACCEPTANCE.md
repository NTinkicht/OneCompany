# First-Run Company Acceptance

Do not raise a fresh installation to continuous autonomy because the configuration files parse. Prove the company loop in a disposable setup Work Unit first.

## Phase A - static control plane

```bash
python onecompany.py doctor
python onecompany.py validate
python onecompany.py simulate
python onecompany.py readiness --local-probe
python onecompany.py audit-github
```

Expected: control-plane invariants pass; GitHub protection/permission warnings are understood; no actor is considered ready merely from subscription ownership.

## Phase B - read mesh

For every enabled actor:

1. read `AGENTS.md`;
2. identify repository + default branch;
3. inspect a known Work Unit/PR/head;
4. produce a bounded artifact;
5. prove a read-only task leaves `git status` clean when local/CLI based.

Record surface/capability evidence in `.onecompany/readiness.json`.

## Phase C - single writer

Create `WU-SETUP-001` with a harmless documentation change.

- grant one implementation lease;
- use one branch/PR;
- implementer pushes one small change;
- CI runs;
- no other actor writes to the stream.

Prove the lease/stream discipline before using a production feature.

## Phase D - independent review

Assign a different, non-author actor. The review must:

- name the exact candidate SHA;
- inspect original evidence;
- verify acceptance criteria;
- check required CI;
- publish the canonical verdict.

Then make a tiny additional material commit and confirm the previous gate is treated as stale.

## Phase E - remediation/failover

Exercise at least one controlled failover:

1. mark the primary implementer's `implementation` capability temporarily unavailable;
2. route a replacement;
3. preserve the same WU/branch/PR/history;
4. continue work;
5. preserve all material authors;
6. use an eligible non-author final reviewer.

Also test capability-specific degradation: mark only `code_review` unavailable while leaving implementation routable.

## Phase F - expected-head merge

With human approval at L1/L2, verify the mechanical merge path refuses or stops if the PR head differs from the approved SHA. Then merge the unchanged approved head.

## Phase G - cost circuit breaker

Attempt to route a cost class forbidden by `.onecompany/budget.json`. Confirm it is rejected. Do not perform a billable provider call for this test.

## Phase H - unattended lanes (only if enabled)

For each unattended actor:

- trusted trigger works;
- untrusted trigger is ignored;
- tool permissions enforce the intended boundary;
- timeout works;
- secrets do not appear in logs/output;
- a harmless task produces a durable result;
- provider/quota failure produces a safe classified status without paid fallback;
- generic scout wake cannot merge/write/gate unless separately authorized.

## Phase I - no-idle / stale lease

At L4+, simulate ready work with no lease and verify the company detects the fault. Simulate a stale-looking lease while CI is actively running and verify it does **not** duplicate implementation before reconciling live evidence.

## Acceptance record

Keep a setup issue containing links to the WU, branch, PR, CI, review, failover evidence, merge evidence, and any unattended smoke runs. Do not paste credentials.

Only raise autonomy when the relevant phases are green and incident/stop procedures are understood.
