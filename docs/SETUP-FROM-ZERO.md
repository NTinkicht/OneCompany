# OneCompany Setup From Zero

This is the end-to-end path from an ordinary GitHub repository to a verified autonomous company.

## 0. Decide authority and budget first

Define repository scope, protected branches, sensitive data, deterministic CI, additional AI spend, human-only actions, intended autonomy and whether unattended operation is allowed. Start at L1/L2.

## 1. Bootstrap

```bash
python onecompany.py bootstrap \
  --target /path/to/project \
  --repository owner/repo \
  --initialize-contracts
```

Bootstrap initializes the target identity and fresh queue/state; it does not copy OneCompany's operational history. Existing `.onecompany` installs must use `docs/UPGRADING.md`.

## 2. Fill project contracts

Complete/map equivalents for `PRODUCT.md`, `ARCHITECTURE.md`, `SECURITY.md`, `QUALITY.md`, and `OPERATIONS.md`. See `docs/PROJECT-CONTRACTS.md`.

## 3. Harden GitHub and CI

Follow `docs/GITHUB-SETUP.md`, protect the default branch, require PRs/material checks, minimize Actions permissions and establish the application-specific deterministic CI recorded in `QUALITY.md`.

```bash
python onecompany.py audit-github
```

## 4. Configure actors

Use `docs/agent-setup/README.md`. For each worker: install/connect, authenticate using the intended cost path, grant least privilege, smoke-test read/write/review/merge separately, record non-secret readiness evidence, then enable only proven capabilities.

A minimum useful company has an implementation route, deterministic CI, and an independent reviewer (which may initially be `human-owner`).

## 5. Configure routing

Review `actors.json`, `readiness.json`, `roles.json`, and `routing.json`.

```bash
python onecompany.py route --capability implementation
python onecompany.py route --capability code_review --for-independent-gate --exclude-author <actor>
```

## 6. Configure executable dispatch paths

Routing says **who** should work; `dispatch.json` says **how they can actually be started**. Configure only mechanisms you have tested and record evidence.

```bash
python onecompany.py dispatch --actor <actor> --capability <capability>
```

For unattended writing, OneCompany requires a durable active lease and the `--unattended --lease-id ...` path. See `docs/DISPATCH-AND-WAKE.md`.

## 7. Create the Team Room and durable ledger before L3+

Create a permanent issue from `.github/ISSUE_TEMPLATE/team-room.md`. Configure `.onecompany/ledger.json` with that issue number and trusted GitHub publisher identities.

The ledger stores lease/failover/material-authorship/gate events outside the implementation SHA. L3+ autonomous delivery and L4/L5 continuous supervision require it in the reference model.

```bash
python onecompany.py ledger read --events
```

See `docs/DURABLE-COORDINATION-LEDGER.md`.

## 8. Review patterns/overlays

Keep core invariants and select only useful specialist overlays. An overlay never creates actor identity, capacity, credentials, lease, independence or merge authority.

## 9. Seed bounded Work Units

Fresh bootstrap leaves `queue.json` empty. Add project WUs/dependencies and verify:

```bash
python onecompany.py next-work
```

## 10. Prove one complete delivery loop

On a harmless WU:

```text
route -> dispatch check -> durable lease -> implementation -> CI
-> independent exact-head durable gate -> same-stream failover drill
-> expected-head merge -> reconcile -> next work
```

Use `docs/FIRST-RUN-ACCEPTANCE.md`.

## 11. Optional unattended provider lanes

Review `docs/UNATTENDED-AUTOMATION.md`. Templates under `.onecompany/templates/` are disabled by default. Verify current provider docs, cost/auth path, trusted triggers, version pins, tool allowlists, timeouts and redaction before enabling.

## 12. 24/7 supervision

Use `docs/SCHEDULED-SUPERVISION.md`.

Preferred architecture:

```text
event-driven handoff
        +
scheduled reconciliation
        +
durable shared ledger
        +
daily scheduler-health verification
```

The optional ChatGPT profile uses four hourly supervisors staggered at approximately `:02`, `:17`, `:32`, `:47` for an effective ~15-minute check. They must all read the same live GitHub + ledger state, acquire the canonical lease before dispatching a writer, and stay quiet while healthy work is progressing.

For an unattended write transition:

```text
supervisor detects work
  -> route eligible actor
  -> acquire durable canonical lease (first valid claim wins)
  -> resolve verified unattended dispatch mechanism for that lease
  -> start worker
```

If any step fails, surface `CAPACITY_BLOCKED`/a real blocker; do not invent another paid path or competing branch.

## 13. Stop/incident drill

Prove you can pause/delete external schedules, disable event tasks/workflows, lower autonomy, disable actors and revoke unattended write credentials. Review `docs/INCIDENT-RUNBOOK.md`.

## Final checks

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

Then complete `docs/ADOPTION-CHECKLIST.md` and `docs/FIRST-RUN-ACCEPTANCE.md` before raising autonomy.
