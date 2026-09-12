# Bootstrap OneCompany

OneCompany supports two safe starts. Choose exactly one.

## A. New repository created from the OneCompany GitHub template

After creating the new repository from OneCompany, initialize the copied control plane once:

```bash
python onecompany.py init \
  --repository OWNER/REPO \
  --project-name "My Product" \
  --initialize-contracts

python onecompany.py check
python onecompany.py doctor
python onecompany.py status --live
```

`init` resets OneCompany source identity, queue, leases, actor readiness, dispatch, ledger and supervision. All autonomous/unattended paths remain disabled. A second init is refused.

## B. Existing product repository

From a trusted OneCompany checkout:

```bash
python onecompany.py bootstrap \
  --target /path/to/product \
  --repository OWNER/REPO \
  --project-name "My Product" \
  --initialize-contracts
```

Bootstrap refuses a target that already contains `.onecompany`; upgrades use `docs/UPGRADING.md`.

## What the starter contracts do

When `--initialize-contracts` is used, missing project contracts are created without overwriting existing ones:

- `PRODUCT.md` — product promise, scope, users, non-goals;
- `ARCHITECTURE.md` — system boundaries/invariants/data/concurrency;
- `SECURITY.md` — auth/authz, privacy, trust and sensitive-data boundaries;
- `QUALITY.md` — deterministic CI/test/reproducibility contract;
- `DESIGN.md` — design system, states, accessibility, responsive/localization/visual quality;
- `OPERATIONS.md` — deploy, rollback, recovery, observability and runbooks.

Fill these before asking agents to make broad product decisions.

## Configure in this order

1. **Human policy first:** repository scope, zero/finite spend, human-only actions, initial L1/L2, emergency stop understood.
2. **GitHub protection:** PR flow, required project CI, no force-push/delete on protected default branch, least-privilege Actions permissions.
3. **Project CI:** exact deterministic commands for the application itself. OneCompany validation does not replace product tests.
4. **Actors:** follow `docs/agent-setup/`; configure only workers you actually own.
5. **Readiness:** smoke read/write/review/merge/unattended separately and record non-secret evidence.
6. **Routing/dispatch:** confirm each routed actor has a real execution path; selection without dispatch is not work.
7. **Team Room/ledger:** before L3/L4 distributed operation, configure the durable coordination issue and trusted publisher identity.
8. **First Work Unit:** low-risk WU, one canonical branch/PR, one lease, deterministic CI, independent exact-head review.
9. **First-run acceptance:** complete `docs/FIRST-RUN-ACCEPTANCE.md` including failover, stale-gate, expected-head, budget and emergency-stop drills.
10. **24/7 supervision:** enable event handoffs first; scheduled supervisors are redundancy. Four staggered ChatGPT hourly supervisors may provide ~15-minute liveness checks, but all are replicas of one supervisor and must obey the durable canonical lease.
11. **Raise autonomy deliberately:** L3 only after autonomous delivery is proven; L4 only after deterministic ready-work selection + ledger + supervision are proven.

## Golden local check

```bash
python onecompany.py check
```

It runs schema/control-plane validation, core/ledger/supervision simulations, fresh-bootstrap smoke, GitHub-template-init smoke and Python compilation. It is deterministic and does not require provider calls.

Then inspect account/repository reality:

```bash
python onecompany.py doctor
python onecompany.py readiness --local-probe
python onecompany.py audit-github
python onecompany.py status --live
```

## Governance-sensitive changes

Read `docs/TRUSTED-CONTROL-PLANE.md`. A candidate PR cannot make its own weaker rules authoritative. Constitution/control-plane changes are evaluated under the trusted base policy and require the human merge boundary in the reference model.
