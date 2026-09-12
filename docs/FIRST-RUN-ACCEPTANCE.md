# First-Run Company Acceptance

Do not raise a fresh installation to continuous autonomy because configuration files parse. Prove both the **happy path and the refusal paths** in a disposable setup Work Unit first.

## Phase 0 — authoritative project contracts

Verify usable product, architecture, security, quality/CI, design/experience (if user-facing), and operations contracts or explicit equivalents. Ask two independent workers to summarize a key invariant; unresolved disagreement means the contract is still ambiguous.

## Phase A — deterministic foundation

```bash
python onecompany.py check
python onecompany.py doctor
python onecompany.py readiness --local-probe
python onecompany.py audit-github
python onecompany.py status --live
python onecompany.py supervise --force-observe
```

Expected: schemas + cross-file/governance/hardening checks pass; simulations/smokes pass; GitHub warnings are understood; no actor becomes ready from subscription ownership alone; supervision is disabled/observe-only.

## Phase B — read mesh

For every enabled actor, prove it can read trusted instructions/project contracts, identify repository/default branch/current WU/PR/head, and produce a bounded artifact. A read-only local/CLI task leaves the worktree clean. Record readiness evidence.

## Phase C — single writer + lease race

Create a harmless setup WU. Prove one canonical branch/PR/lease. Attempt a competing implementation claim and confirm the canonical first valid durable lease wins. No losing supervisor/worker may continue writing.

## Phase D — independent exact-head review

Use a non-author actor. Review exact SHA + original evidence + acceptance criteria + required CI. Prove:

- a material commit stales the old gate;
- adding the reviewer to durable material authorship also stales the gate even if code SHA is unchanged;
- a merge-ready gate with no durable evidence is refused.

## Phase E — remediation/failover

Degrade implementation for the primary actor, route a replacement on the **same WU/branch/PR**, preserve cumulative material authorship, and finish with a still-independent reviewer. Separately degrade only review capability and verify implementation remains routable when appropriate.

## Phase F — expected-head + reviewer revalidation

With human approval at L1/L2, prove merge refuses:

- head different from approved SHA;
- stale gate;
- reviewer who is now a material author;
- reviewer whose review capability/access became unavailable;
- required checks not reported/green;
- open human-decision/blocker state.

Then merge only the unchanged approved head.

## Phase G — deterministic queue progression

Build a tiny dependency graph. Confirm:

- only `READY` is executable autonomously;
- `PROPOSED` stays planning-only;
- missing dependencies and dependency cycles are detected;
- durable `MERGED` evidence can unlock downstream READY work across independent runs;
- active canonical implementation suppresses starting a second stream;
- no READY work means legitimate idle.

## Phase H — cost circuit breaker

Attempt a forbidden/unknown cost route and confirm refusal **without making a billable provider call**. Prove quota exhaustion becomes capacity degradation rather than paid fallback.

## Phase I — emergency stop / incident containment

Activate emergency stop in a disposable setup and prove:

- new lease acquisition/transfer is refused;
- unattended/write dispatch is refused;
- binding gate publication is refused;
- merge is refused;
- read-only status/supervision/reconciliation can still diagnose;
- safe lease release/credential revocation path remains available;
- normal mutation does not resume until the authorized human clears containment after reconciliation.

## Phase J — trusted control-plane negative test

Create a disposable PR proposing weaker `AGENTS.md`/governance/merge rules. Confirm the candidate rules do **not** become authority over their own review. Use trusted base/pinned-prior policy, and confirm protected control-plane changes require the human merge boundary.

## Phase K — user-facing experience (if applicable)

For a representative UI WU, prove the selected deterministic evidence is appropriate: state completeness, keyboard/focus/accessibility, responsive/device behavior, localization/RTL/theme where relevant, intentional visual baseline changes, and stable performance/bundle budgets where configured. Do not require irrelevant UI evidence for backend-only work.

## Phase L — unattended lanes (only if enabled)

For each unattended actor prove trusted trigger, untrusted-trigger rejection, real dispatch mechanism, canonical lease for writing, tool boundary, timeout, secret redaction, durable result, safe provider/quota failure, and no unauthorized gate/merge.

## Phase M — 24/7 supervision (only if enabled)

Prove:

- event-driven transition requests the next bounded capability;
- scheduled supervisor observes healthy work and stays quiet;
- four staggered external supervisors cannot create duplicate canonical leases/PRs;
- stale-looking lease with live CI/job movement is not failed over;
- READY work with no lease creates one canonical routing/lease action;
- scheduler failure/disablement becomes visible;
- scheduled tasks read GitHub authority rather than relying on conversation/Project files;
- approval-required action becomes a visible human blocker;
- stopping all supervisors cleanly stops continuous operation.

## Phase N — supply-chain / schema refusal tests

Prove validation rejects at least one controlled fixture for each relevant class: malformed control document, unpinned managed Action, managed `pull_request_target`, managed `write-all`, and accidental executable provider template.

## Acceptance record

Keep one setup issue with links to contracts, WU, PR, CI, independent review, failover, expected-head refusal, emergency-stop drill, queue test, scheduler/unattended evidence and any accepted residual risks. Never paste credentials.

Only raise autonomy after the relevant phases are green. Increasing autonomy is a human decision in the reference constitution.
