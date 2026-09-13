# OneCompany Release / Production Readiness Checklist

Use this before treating a OneCompany installation as production-grade or publishing OneCompany itself as a reusable CompanyOS starter.

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
- [ ] Planning/assurance/merge/runtime authority files are protected control-plane paths
- [ ] Protected control-plane merge path uses trusted base/pinned prior executor or direct authorized-human merge
- [ ] Emergency stop and credential revoke path tested

## Planning baseline
- [ ] Objective/Epic/Capability hierarchy is coherent for the project
- [ ] Formal requirements are approved, unambiguous and verifiable
- [ ] Acceptance-criterion references resolve to canonical definitions
- [ ] Planning risk register is current and score math is valid
- [ ] Critical residual risks have explicit human acceptance
- [ ] Active WUs trace bidirectionally to planning parents and/or requirements
- [ ] WU dependency graph is acyclic
- [ ] WU write scopes and semantic resource locks are declared before parallel admission
- [ ] Estimates/confidence are treated as forecasts, not commitments

## Deterministic acceptance

```bash
python onecompany.py check
python onecompany.py validate
python onecompany.py doctor
python onecompany.py audit-github
python onecompany.py status --live
python onecompany.py simulate-parallel
```

- [ ] All deterministic checks green
- [ ] No ignored/flaky required failure hidden by retries
- [ ] JSON schemas + cross-file invariants green
- [ ] Planning/risk/flow validators green
- [ ] Durable-ledger race/staleness simulations green
- [ ] Parallel conflict/WIP/actor-capacity simulations green
- [ ] Fresh bootstrap + template-init smokes green
- [ ] Guided onboarding read-only/no-overwrite behavior tested
- [ ] Managed workflow supply-chain audit green

## Agents / cost / capacity
- [ ] Every enabled actor has current readiness evidence
- [ ] Every enabled implementation actor has explicit verified capacity
- [ ] Every unattended actor has a tested dispatch mechanism
- [ ] Independent reviewer route exists after authorship exclusions
- [ ] Merge-executor route exists or human merge is documented
- [ ] Spend policy matches actual account/provider path
- [ ] No silent metered fallback/overage/top-up/new vendor

## Safe parallel delivery
- [ ] Exactly one canonical implementation stream exists per WU
- [ ] Independent WUs may coexist only when dependency/scope/lock/risk/WIP/capacity checks pass
- [ ] Missing/unknown write scope serializes rather than assuming safety
- [ ] Critical-risk work serializes by default unless stricter reviewed policy explicitly permits otherwise
- [ ] Live PR changed files are checked against declared WU scope
- [ ] Merging/releasing one WU leaves unrelated active WU leases intact
- [ ] Failover changes the worker, not the canonical stream or authorship history

## Integration evidence
- [ ] Required CI is green on the exact candidate head SHA
- [ ] Binding review/gate records the exact candidate base SHA as well as head SHA
- [ ] Base movement after another merge invalidates previous integration evidence
- [ ] Material authorship snapshot is current
- [ ] Independent reviewer is not a material author
- [ ] Required evidence references are durable
- [ ] Merge revalidates live scope, head, base, reviewer eligibility, CI and governance sensitivity

## Delivery / data safety
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
- [ ] Concurrent supervisor same-WU lease race test passed
- [ ] Independent-WU parallel admission test passed
- [ ] Capacity failure produces degradation/blocking rather than invented success
- [ ] READY-but-non-executable work does not trigger a false no-idle fault
- [ ] Legitimate idle remains legitimate
- [ ] Post-merge portfolio recomputation releases newly unblocked work safely

## Learning loop
- [ ] Release artifact traces to exact merged SHA/WUs
- [ ] Observability/health/smoke verification exists
- [ ] Outcomes and escaped defects are captured
- [ ] Escaped defects feed regression tests/requirements/risks/fitness functions where applicable
- [ ] Retrospective findings update the approved baseline through reviewed change control

## Final promotion
- [ ] Exact candidate head **and base** CI/integration evidence green
- [ ] Independent non-author exact-head/base review complete
- [ ] All required-severity findings reconciled
- [ ] Any human-only decisions relevant to this release resolved
- [ ] Authorized-human merge used for protected OneCompany/control-plane changes
- [ ] Post-merge reconciliation/status check completed
