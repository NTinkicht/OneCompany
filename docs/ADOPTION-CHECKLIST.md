# Adoption Checklist

## Project contracts
- [ ] Product problem/users/scope/non-goals captured in `PRODUCT.md` or equivalent
- [ ] Architecture/data/interface/concurrency boundaries captured
- [ ] Security/auth/authorization/secrets/sensitive-data invariants captured
- [ ] Deterministic quality/CI contract captured
- [ ] Deployment/rollback/operations boundaries captured where relevant

## Governance
- [ ] Source of truth declared as GitHub
- [ ] Initial autonomy level selected (L1/L2 recommended)
- [ ] Human-only decisions documented
- [ ] Stop/revoke mechanism understood
- [ ] Pattern library reviewed; project-specific replacements documented

## Budget
- [ ] Additional AI spend cap set
- [ ] Paid fallback policy explicit
- [ ] Overage/top-up policy explicit
- [ ] CI/runner cost considered
- [ ] Every enabled actor has an understood cost class
- [ ] API-key paths are not assumed equivalent to subscription access

## GitHub
- [ ] Default branch/ruleset/protection reviewed
- [ ] PR flow for material changes established
- [ ] Required deterministic checks configured
- [ ] Force push/default-branch deletion controlled
- [ ] Actions default token permissions reviewed
- [ ] `python onecompany.py audit-github` warnings understood

## Workers
- [ ] Each intended actor has its provider setup guide completed
- [ ] Actor/readiness records exist
- [ ] Enabled actors are actually configured
- [ ] Read/write/review/merge capabilities smoke-tested separately as needed
- [ ] Capability-specific quota degradation can be represented
- [ ] Write permissions are least privilege
- [ ] Independent reviewer route exists
- [ ] Fallback route exists or visible capacity-block behavior is accepted
- [ ] No actor can sole-gate its own material authorship
- [ ] Actor retirement/credential rotation process understood

## Provider-specific
- [ ] ChatGPT GitHub read connection is not mistaken for write authority
- [ ] Codex native/workspace Git path verified if used
- [ ] Claude interactive/Action auth and cost path understood if used
- [ ] Copilot cloud-agent/review repository access and Actions implications reviewed if used
- [ ] Gemini auth path classified; paid Vertex/API fallback not silently enabled
- [ ] Mistral plan/PAYG state verified; key validity is not cost proof
- [ ] Custom/local actors document auth, cost, permissions, stop path and smoke evidence

## Delivery
- [ ] WU template adopted
- [ ] Queue contains project work only, not OneCompany template history
- [ ] Dependency-ready selection tested with `python onecompany.py next-work`
- [ ] Single-stream lease invariant accepted
- [ ] Deterministic project CI contract defined
- [ ] Exact-head review required
- [ ] Expected-head merge available/manual equivalent documented
- [ ] Material authorship tracked across failover/cherry-pick/replay

## Coordination / 24x7
- [ ] Team Room/durable coordination bus chosen when needed
- [ ] Heartbeats are visibility, not proof of work
- [ ] Stale lease requires live-evidence reconciliation before failover
- [ ] Event-driven handoff path selected where available
- [ ] Scheduled reconciliation policy reviewed
- [ ] If using four ChatGPT supervisors, hourly tasks are staggered rather than racing together
- [ ] Scheduled tasks read authoritative contracts/state from GitHub rather than assuming ChatGPT Project files are available
- [ ] Scheduler health is checked and failures are visible
- [ ] GitHub schedule cadence/Actions cost reviewed
- [ ] Legitimate idle with no READY work is allowed

## Unattended operation
- [ ] Unattended execution remains disabled until explicitly reviewed
- [ ] Trusted trigger restriction configured
- [ ] Tool permissions/allow-list enforced
- [ ] Hard timeout/turn/output limits configured
- [ ] Log/result redaction tested
- [ ] Provider/version pinned or deliberately controlled
- [ ] Billing guard configured where needed
- [ ] Generic scout wake is non-gating/read-only by default
- [ ] Stop/revoke path tested

## Security
- [ ] Secrets excluded from prompts/state/logs
- [ ] Credentials use the correct platform secret store
- [ ] Untrusted PR/issue/source text treated as data, not governance
- [ ] Prompt-injection hierarchy understood
- [ ] Credential/permission expansion is human-only by default
- [ ] Fork/untrusted PR workflow secret exposure reviewed

## Operations
- [ ] `python onecompany.py doctor` passes
- [ ] `python onecompany.py validate` passes
- [ ] `python onecompany.py simulate` passes
- [ ] `python onecompany.py simulate-supervision` passes
- [ ] `python onecompany.py readiness --local-probe` reviewed
- [ ] `python onecompany.py supervise --force-observe` behaves correctly
- [ ] Incident runbook reviewed
- [ ] First-run acceptance plan completed
- [ ] Controlled failover tested on same branch/PR
- [ ] Stale exact-head review invalidation tested
- [ ] Cost circuit breaker tested without a billable call
- [ ] Scheduler stop/disable drill tested if 24/7 supervision is enabled
