# Adoption Checklist

## Governance
- [ ] Source of truth declared as GitHub
- [ ] Autonomy level selected
- [ ] Human-only decisions documented
- [ ] Stop mechanism understood

## Budget
- [ ] Additional AI spend cap set
- [ ] Paid fallback policy explicit
- [ ] Overage/top-up policy explicit
- [ ] CI/runner cost considered

## Workers
- [ ] Actors registered
- [ ] Enabled actors actually configured
- [ ] Write permissions least-privilege
- [ ] Independent reviewer route exists
- [ ] Fallback route exists or visible capacity-block behavior accepted

## Delivery
- [ ] WU template adopted
- [ ] Single-stream lease invariant accepted
- [ ] Deterministic CI contract defined
- [ ] Exact-head review required
- [ ] Expected-head merge available/manual equivalent documented

## Security
- [ ] Secrets excluded from prompts/state/logs
- [ ] Untrusted PR model reviewed
- [ ] Prompt-injection hierarchy understood
- [ ] Credential expansion is human-only

## Operations
- [ ] `doctor.py` passes
- [ ] `validate.py` passes
- [ ] `simulate.py` passes
- [ ] Incident runbook reviewed
- [ ] At least drills 1-8 in `SIMULATION.md` completed before L4+
