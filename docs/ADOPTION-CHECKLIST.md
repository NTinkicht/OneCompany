# Adoption Checklist

## Product truth
- [ ] Product problem/users/scope/non-goals captured
- [ ] Architecture/data/interface/concurrency boundaries captured
- [ ] Security/auth/authorization/secrets/sensitive-data invariants captured
- [ ] Deterministic quality/CI contract captured
- [ ] Deployment/rollback/operations boundaries captured where relevant

## Governance / budget
- [ ] GitHub declared operational source of truth
- [ ] Initial L1/L2 autonomy selected
- [ ] Human-only decisions documented
- [ ] Stop/revoke mechanism understood
- [ ] Additional AI spend cap explicit
- [ ] Paid fallback/overage/top-up/new-vendor rules explicit
- [ ] CI/runner cost considered
- [ ] API-key billing paths not assumed equivalent to subscriptions

## GitHub
- [ ] Default branch/ruleset/protection reviewed
- [ ] PR flow and required deterministic checks configured
- [ ] Force push/deletion policy reviewed
- [ ] Actions token permissions reviewed
- [ ] `python onecompany.py audit-github` warnings understood

## Actors / readiness
- [ ] Each enabled actor completed its provider setup runbook
- [ ] Actor/readiness records match
- [ ] Read/write/review/merge capabilities smoke-tested separately as needed
- [ ] Capability-specific quota degradation is representable
- [ ] Independent reviewer route exists
- [ ] Fallback route or explicit capacity-block behavior exists
- [ ] No actor may sole-gate its own material authorship
- [ ] Credential rotation/actor retirement process understood

## Dispatch
- [ ] Every autonomous role has at least one real configured execution/wake path
- [ ] `dispatch.json` evidence reflects tested mechanisms
- [ ] Routing is never treated as proof that a worker actually started
- [ ] Unattended write dispatch requires canonical durable lease
- [ ] Generic scout wake remains non-gating/read-only unless separately authorized

## Durable coordination
- [ ] Team Room issue created if using distributed autonomy
- [ ] `ledger.json` issue number configured
- [ ] Trusted publisher GitHub logins explicitly configured
- [ ] Untrusted ledger markers are ignored
- [ ] First-valid implementation lease wins concurrent claims
- [ ] Same-stream failover uses durable transfer
- [ ] Material authorship survives failover/replay
- [ ] Final L3+ gate lives outside the implementation SHA in durable GitHub evidence

## Delivery
- [ ] WU template adopted
- [ ] Fresh queue contains project work only
- [ ] `python onecompany.py next-work` tested
- [ ] Single canonical implementation stream accepted
- [ ] Exact-head review required
- [ ] Expected-head merge available/manual equivalent documented
- [ ] Controlled same-stream failover tested

## 24/7 supervision
- [ ] Event-driven handoff selected where available
- [ ] Scheduled reconciliation policy reviewed
- [ ] Four ChatGPT supervisors, if used, are staggered rather than concurrent by schedule
- [ ] All supervisors read live GitHub + shared durable ledger
- [ ] Scheduled task does not assume ChatGPT Project files are accessible
- [ ] Healthy CI/work is not preempted
- [ ] Stale suspicion is reconciled against live job/branch evidence before failover
- [ ] Ready work creates at most one canonical durable lease
- [ ] Scheduler health checked and failure is visible
- [ ] GitHub Actions cadence/cost reviewed
- [ ] Legitimate idle with no ready work is allowed

## Unattended execution/security
- [ ] Trusted triggers configured
- [ ] Tool permissions/allowlists enforced
- [ ] Hard timeout/turn/output limits configured
- [ ] Log/result redaction tested
- [ ] Provider/version pinned or deliberately controlled
- [ ] Billing guard configured where needed
- [ ] Secrets excluded from prompts/state/logs/coordination comments
- [ ] Fork/untrusted content trust boundary understood

## Acceptance
- [ ] `python onecompany.py doctor` passes
- [ ] `python onecompany.py validate` passes
- [ ] `python onecompany.py simulate` passes
- [ ] `python onecompany.py simulate-supervision` passes
- [ ] `python onecompany.py readiness --local-probe` reviewed
- [ ] Bootstrap smoke is green in OneCompany CI
- [ ] Exact-head stale-review invalidation tested
- [ ] Concurrent lease race tested or understood through ledger invariant
- [ ] Cost circuit breaker tested without billable call
- [ ] Scheduler stop/disable drill tested when 24/7 mode is enabled
- [ ] `docs/FIRST-RUN-ACCEPTANCE.md` completed before L3/L4 elevation
