# OneCompany Release / Production Readiness Checklist

Use this before treating a OneCompany installation as production-grade or publishing OneCompany itself as a reusable starter.

## Repository owner controls
- [ ] Software license chosen and committed
- [ ] Default branch protected
- [ ] Required product + OneCompany checks configured
- [ ] Force-push/deletion policy reviewed
- [ ] Admin/secret changes remain human-controlled
- [ ] Intended merge method selected
- [ ] Auto-merge remains off unless proven autonomy warrants it
- [ ] If distributing OneCompany through GitHub, **Template repository** setting enabled deliberately

## Trusted control plane
- [ ] Constitution and governance policy reviewed
- [ ] Candidate governance cannot govern its own approval
- [ ] Protected control-plane merge path uses trusted base/pinned prior executor or direct authorized-human merge
- [ ] Emergency stop and credential revoke path tested

## Deterministic acceptance

```bash
python onecompany.py check
python onecompany.py doctor
python onecompany.py audit-github
python onecompany.py status --live
```

- [ ] All deterministic checks green
- [ ] No ignored/flaky required failure hidden by retries
- [ ] JSON schemas + cross-file invariants green
- [ ] Durable-ledger race/staleness simulations green
- [ ] Fresh bootstrap + template-init smokes green
- [ ] Managed workflow supply-chain audit green

## Agents / cost
- [ ] Every enabled actor has current readiness evidence
- [ ] Every unattended actor has a tested dispatch mechanism
- [ ] Independent reviewer route exists after authorship exclusions
- [ ] Merge-executor route exists or human merge is documented
- [ ] Spend policy matches actual account/provider path
- [ ] No silent metered fallback/overage/top-up

## Delivery / data safety
- [ ] READY-only queue semantics accepted
- [ ] Dependency graph valid
- [ ] External side effects idempotent/deduplicated
- [ ] Retry policies bounded
- [ ] Database/destructive work has tested recovery strategy
- [ ] Deployment rollback/restore documented
- [ ] Sensitive-data/logging boundaries reviewed

## User-facing quality when applicable
- [ ] Design system/source of truth documented
- [ ] UI state completeness tested
- [ ] Accessibility/keyboard/focus tested
- [ ] Responsive/localization/RTL/theme cases tested as relevant
- [ ] Visual/performance regressions intentional and stable

## Continuous autonomy when applicable
- [ ] Event-driven handoff works
- [ ] Durable ledger shared by all independent supervisors
- [ ] Schedule redundancy configured only after cost review
- [ ] Scheduler health is visible
- [ ] Concurrent supervisor lease race test passed
- [ ] Capacity failure produces degradation/blocking rather than invented success
- [ ] Legitimate idle remains legitimate

## Final promotion
- [ ] Exact candidate SHA CI green
- [ ] Independent non-author exact-head review complete
- [ ] All required-severity findings reconciled
- [ ] Any human-only decisions resolved
- [ ] Human merge used for protected OneCompany/control-plane changes
- [ ] Post-merge reconciliation/status check planned
