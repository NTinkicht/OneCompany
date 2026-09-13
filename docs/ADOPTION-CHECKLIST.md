# Adoption Checklist

## Governance / safety
- [ ] GitHub is source of truth; local state/chat are not authority
- [ ] Initial autonomy selected (L1/L2 recommended)
- [ ] Human-only decisions documented
- [ ] Emergency stop understood and tested
- [ ] No-self-escalation / trusted-base control-plane rule understood
- [ ] Protected control-plane changes require human merge under reference policy
- [ ] Stop/revoke/credential containment path tested
- [ ] Pattern library reviewed; replacements preserve the invariant

## Product truth
- [ ] PRODUCT/ARCHITECTURE/SECURITY/QUALITY/OPERATIONS contracts or equivalents exist
- [ ] DESIGN/experience contract exists if project has user-facing UI
- [ ] Non-goals and destructive/irreversible boundaries are explicit

## Budget
- [ ] Additional AI spend cap set
- [ ] Paid fallback/overage/auto-top-up/new-vendor policy explicit
- [ ] CI/runner/provider cost considered
- [ ] Every enabled actor has classified cost path
- [ ] API key validity is not treated as proof of subscription/included capacity

## GitHub / supply chain
- [ ] Default branch protection/ruleset reviewed
- [ ] PR flow for material changes established
- [ ] Required deterministic product checks configured
- [ ] Force push/default-branch deletion controlled
- [ ] Actions default token permissions reviewed
- [ ] Managed external Actions pinned by immutable SHA
- [ ] No managed `pull_request_target` / `permissions: write-all`
- [ ] `python onecompany.py audit-github` warnings understood

## Workers / readiness
- [ ] Provider setup guide completed for each intended actor
- [ ] Actor declared, configured and enabled only after smoke evidence
- [ ] Read/write/review/merge/unattended capabilities tested separately
- [ ] Capability-specific quota degradation can be represented
- [ ] Repository permissions are least privilege
- [ ] Independent review route exists
- [ ] Failover route or visible `CAPACITY_BLOCKED` behavior exists
- [ ] No actor can sole-gate its material authorship

## Delivery / determinism
- [ ] WU template adopted
- [ ] Only READY work is autonomously executable
- [ ] Dependency graph has no missing nodes/cycles
- [ ] One canonical stream/lease accepted
- [ ] Deterministic project CI commands documented
- [ ] Seed/time/locale/network/runtime sources of nondeterminism considered
- [ ] Flaky tests are not retried until green
- [ ] Exact-head review + merge-time reviewer revalidation required
- [ ] Material authorship survives failover/replay/cherry-pick
- [ ] External side effects have idempotency/deduplication + bounded retry
- [ ] Destructive changes have rollback/restore/compensation

## Design / UI when applicable
- [ ] Canonical design tokens/components identified
- [ ] Important loading/empty/validation/error/degraded/recovery states defined
- [ ] Accessibility + keyboard/focus acceptance exists
- [ ] Responsive/device matrix exists
- [ ] Localization/RTL/theme cases selected where relevant
- [ ] Visual regression/performance checks are stable enough to provide signal
- [ ] Human judgment evidence remains proportional to change

## Coordination / 24x7
- [ ] Team Room/durable ledger chosen for multi-run autonomy
- [ ] Trusted publisher credential treated as high impact
- [ ] Heartbeat is telemetry, not progress
- [ ] Stale lease requires live evidence reconciliation before failover
- [ ] Event-driven handoffs preferred; schedules provide redundancy
- [ ] Four-staggered supervisor pattern, if used, shares one durable canonical lease
- [ ] Scheduler health is monitored
- [ ] Supervisors can be disabled cleanly

## Unattended security
- [ ] Unattended execution disabled until deliberately reviewed
- [ ] Trusted trigger restriction configured
- [ ] Real dispatch mechanism verified
- [ ] Tool allow-list / hard timeout / output limits enforced
- [ ] Secret and result redaction tested
- [ ] Provider version/cost guard reviewed
- [ ] Generic scout wakes read-only/non-gating by default

## Operations
- [ ] `python onecompany.py check` passes
- [ ] `python onecompany.py doctor` reviewed
- [ ] `python onecompany.py readiness --local-probe` reviewed
- [ ] `python onecompany.py audit-github` reviewed
- [ ] `python onecompany.py status --live` reviewed
- [ ] Incident runbook reviewed
- [ ] First-run acceptance completed
- [ ] Controlled failover, stale-gate, expected-head, cost and emergency-stop drills pass

Only raise autonomy after the relevant evidence is durable and understood.
