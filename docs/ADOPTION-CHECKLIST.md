# Adoption Checklist

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
- [ ] Actors registered in `actors.json`
- [ ] Readiness record exists for every actor
- [ ] Enabled actors are actually configured
- [ ] Read access smoke-tested
- [ ] Write capability smoke-tested separately where needed
- [ ] Review capability smoke-tested separately where needed
- [ ] Merge capability smoke-tested separately where needed
- [ ] Capability-specific quota degradation can be represented without disabling whole actor
- [ ] Write permissions are least privilege
- [ ] Independent reviewer route exists
- [ ] Fallback route exists or visible capacity-block behavior is accepted
- [ ] No actor can sole-gate its own material authorship

## Provider-specific
- [ ] ChatGPT GitHub read connection is not mistaken for write authority
- [ ] Codex native/workspace Git path verified if used
- [ ] Claude interactive/Action surfaces and auth cost path understood if used
- [ ] Copilot cloud-agent/review repository access and cost/Actions implications reviewed if used
- [ ] Gemini authentication path classified; paid Vertex/API fallback not silently enabled
- [ ] Mistral plan/PAYG state verified; key validity is not treated as cost proof
- [ ] Custom/local actors document auth, cost, permissions, stop path, and smoke evidence

## Delivery
- [ ] WU template adopted
- [ ] Single-stream lease invariant accepted
- [ ] Deterministic project CI contract defined
- [ ] Exact-head review required
- [ ] Expected-head merge available/manual equivalent documented
- [ ] Material authorship is tracked across failover/cherry-pick/replay
- [ ] Role overlays cannot manufacture authority/independence

## Coordination
- [ ] Team Room/durable coordination bus chosen when multi-actor coordination needs it
- [ ] Heartbeats are visibility, not proof of work
- [ ] Stale lease requires live-evidence reconciliation before failover
- [ ] Slack/Discord/Teams, if used, are attention layers rather than a second state machine

## Unattended operation
- [ ] Unattended execution remains disabled until explicitly reviewed
- [ ] Trusted trigger/actor restriction configured
- [ ] Tool permissions/allow-list enforced
- [ ] Hard timeout/turn/output limits configured
- [ ] Log/result redaction tested
- [ ] Provider/version pinned or deliberately controlled
- [ ] Billing guard configured where needed
- [ ] Generic scout wake is non-gating/read-only by default
- [ ] Stop/revoke path tested

## Security
- [ ] Secrets excluded from prompts/state/logs
- [ ] Credentials use the correct platform-native secret store
- [ ] Untrusted PR/issue/source text treated as data, not governance
- [ ] Prompt-injection hierarchy understood
- [ ] Credential/permission expansion is human-only by default
- [ ] Fork/untrusted PR workflow secret exposure reviewed

## Operations
- [ ] `python onecompany.py doctor` passes
- [ ] `python onecompany.py validate` passes
- [ ] `python onecompany.py simulate` passes
- [ ] `python onecompany.py readiness --local-probe` reviewed
- [ ] Incident runbook reviewed
- [ ] First-run acceptance plan completed
- [ ] At least drills 1-8 in `SIMULATION.md` completed before L4+
- [ ] Controlled implementation failover tested on same branch/PR
- [ ] Stale exact-head review invalidation tested
- [ ] Cost circuit breaker tested without making a billable call
