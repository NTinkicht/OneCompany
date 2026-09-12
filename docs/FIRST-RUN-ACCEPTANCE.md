# First-Run Company Acceptance

Do not raise a fresh installation to continuous autonomy because configuration files parse. Prove the company loop in a disposable setup Work Unit first.

## Phase 0 - authoritative project contracts

Before testing autonomy, verify the repository has a usable product, architecture, security, quality/CI and operations contract (or explicit equivalents). Ask two workers to independently summarize a key invariant; disagreement means the contract is still ambiguous.

## Phase A - static control plane

```bash
python onecompany.py doctor
python onecompany.py validate
python onecompany.py simulate
python onecompany.py simulate-supervision
python onecompany.py readiness --local-probe
python onecompany.py audit-github
python onecompany.py supervise --force-observe
```

Expected: invariants pass; GitHub warnings are understood; no actor is ready merely from subscription ownership; supervision starts disabled/observe-only.

## Phase B - read mesh

For every enabled actor, read `AGENTS.md`, relevant project contracts, repository/default branch and a known WU/PR/head; produce a bounded artifact and prove read-only tasks stay read-only. Record readiness evidence.

## Phase C - single writer

Create a harmless setup WU. Grant one implementation lease, use one canonical branch/PR, make one small change, run CI, and prove no other actor writes to the stream.

## Phase D - independent exact-head review

Use a different non-author actor. Review the exact SHA, original evidence, acceptance criteria and CI. Then make a small material commit and confirm the old gate becomes stale.

## Phase E - remediation/failover

Simulate one implementer capability becoming unavailable. Route a replacement **on the same WU/branch/PR**, preserve material authorship, and complete with an eligible non-author reviewer. Also simulate only review quota degrading while implementation remains available.

## Phase F - expected-head merge

At L1/L2 with human approval, prove the mechanical merge path refuses a head different from the approved SHA, then merge the unchanged approved head.

## Phase G - queue progression

Use `python onecompany.py next-work` on a small dependency graph. Confirm completed dependencies unlock the next WU, missing/unfinished/cancelled dependencies do not, and an active canonical stream suppresses starting new implementation.

## Phase H - cost circuit breaker

Attempt to route a forbidden cost class and confirm rejection without making a billable provider call.

## Phase I - unattended lanes (only if enabled)

For each unattended actor prove trusted trigger, untrusted-trigger rejection, tool boundary, timeout, secret redaction, durable result, safe provider/quota failure, and no unauthorized write/gate/merge.

## Phase J - 24/7 supervision (only if enabled)

Prove:

- event-driven transition can request the next bounded action;
- scheduled supervisor observes healthy work and does nothing;
- four staggered external supervisors do not create duplicate leases/PRs;
- a stale-looking lease with live CI/job movement is **not** failed over;
- ready work with no lease produces one routing action, not four competing writers;
- scheduler failure/disablement becomes visible;
- scheduled-task GitHub access works without relying on ChatGPT Project files;
- any action requiring approval becomes a visible blocker rather than assumed success;
- pause/delete/disable of all supervisors cleanly stops continuous operation.

## Phase K - no-idle

At L4+, simulate READY work with no lease and verify the company detects the fault. Also verify legitimate idle when no dependency-ready work exists.

## Acceptance record

Keep a setup issue with links to contracts, WU, branch, PR, CI, review, failover, merge, scheduler and unattended smoke evidence. Never paste credentials.

Only raise autonomy when the relevant phases are green and incident/stop procedures are understood.
