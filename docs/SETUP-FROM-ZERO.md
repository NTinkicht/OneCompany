# OneCompany Setup From Zero

This is the end-to-end path from a normal GitHub repository to a verified OneCompany installation. It starts safe and raises autonomy only after evidence.

## Stage 0 - decide policy before connecting AI

Write down repository scope, protected branches, sensitive data classes, AI spend cap, human-only actions, initial autonomy (L1/L2 recommended), deterministic CI commands, and whether unattended execution is allowed.

## Stage 1 - bootstrap safely

From a OneCompany checkout:

```bash
python onecompany.py bootstrap \
  --target /path/to/project \
  --repository owner/repo \
  --initialize-contracts
```

`--repository` may be omitted when bootstrap can infer a GitHub `origin`. Bootstrap initializes the target identity, resets queue/state for the **new** company, and never copies OneCompany's own operational WU history. It refuses an existing `.onecompany` install unless forced; use `docs/UPGRADING.md` for upgrades.

## Stage 2 - fill authoritative project contracts

Complete or map equivalents for:

```text
PRODUCT.md
ARCHITECTURE.md
SECURITY.md
QUALITY.md
OPERATIONS.md
```

These are the durable product boundaries beneath the autonomous control plane. See `docs/PROJECT-CONTRACTS.md`.

## Stage 3 - configure GitHub

Follow `docs/GITHUB-SETUP.md`: protect the default branch/ruleset, require PRs for material changes, configure required deterministic checks, control force-push/deletion, minimize Actions token permissions, and keep auto-merge off until L3 is proven.

Run:

```bash
python onecompany.py audit-github
```

Understand every warning.

## Stage 4 - create deterministic project CI

OneCompany validation does not replace application CI. Establish reproducible format/lint/typecheck/test/integration/migration/build/security checks as appropriate and record them in `QUALITY.md` plus WU contracts.

## Stage 5 - configure workers

Use `docs/agent-setup/README.md` and the provider guide for every actor you own.

For each actor: install/connect the intended surface, authenticate without committing secrets, grant minimum repository permissions, smoke-test read/write/review/merge separately as needed, record non-secret evidence in `readiness.json`, then set `configured/enabled` only for routes genuinely usable now.

A minimal safe company needs one implementer route, deterministic CI, and one independent reviewer route; the reviewer may initially be `human-owner`.

## Stage 6 - configure routing and actor lifecycle

Review `actors.json`, `readiness.json`, `roles.json`, and `routing.json`.

```bash
python onecompany.py route --capability implementation
python onecompany.py route --capability code_review --for-independent-gate --exclude-author <actor-id>
```

Read `docs/ACTOR-LIFECYCLE.md` for capability degradation, recovery, credential rotation and retirement.

## Stage 7 - patterns and role overlays

Review `patterns.json` and `overlays.json`. Keep core invariants. Overlays sharpen a real actor's lens but do not create capacity, leases, permissions or independence.

## Stage 8 - Team Room / coordination

Create a permanent Team Room issue from `.github/ISSUE_TEMPLATE/team-room.md` when multi-worker coordination needs it. Put the issue number in `supervision.json` before enabling Team Room posting. Slack/Discord/Teams remain attention layers.

## Stage 9 - seed the project queue

Create bounded WUs and dependencies. The installed queue starts empty by design.

Check dependency-ready work with:

```bash
python onecompany.py next-work
```

The selector refuses to encourage new implementation while a canonical stream is already active.

## Stage 10 - prove the delivery loop

Run `docs/FIRST-RUN-ACCEPTANCE.md` on a harmless setup WU:

```text
lease -> implement -> CI -> independent exact-head gate
-> stale-review invalidation -> same-stream failover
-> expected-head merge -> reconcile -> next work
```

## Stage 11 - optional unattended actors

Read `docs/UNATTENDED-AUTOMATION.md`. Provider/wake templates under `.onecompany/templates/` are deliberately disabled. Enable only after current provider docs, version/cost guards, permissions, timeouts and redaction are verified.

## Stage 12 - round-the-clock supervision

Read `docs/SCHEDULED-SUPERVISION.md` and configure `supervision.json`.

Preferred model:

```text
event-driven handoffs
        +
scheduled reconciliation safety net
        +
daily scheduler-health check
```

Optional profiles include an off-peak hourly GitHub Actions supervisor and four staggered hourly ChatGPT scheduled supervisors giving an effective ~15-minute liveness check. They are **supervisors**, not four writers.

Before enabling 24/7 mode:

```bash
python onecompany.py validate
python onecompany.py simulate-supervision
python onecompany.py supervise --force-observe
```

For L4, also enable no-idle and continuous queue only after the full acceptance drills pass.

## Stage 13 - stop/incident drill

Prove you can pause/delete external schedules, disable workflows, revoke unattended write credentials, disable actors, and lower autonomy. Review `docs/INCIDENT-RUNBOOK.md`.

## Final pre-autonomy command set

```bash
python onecompany.py doctor
python onecompany.py validate
python onecompany.py simulate
python onecompany.py simulate-supervision
python onecompany.py readiness --local-probe
python onecompany.py audit-github
python onecompany.py next-work
python onecompany.py supervise --force-observe
```

Then complete `docs/ADOPTION-CHECKLIST.md` and `docs/FIRST-RUN-ACCEPTANCE.md`.
