# OneCompany Setup From Zero

This is the end-to-end path from a normal GitHub repository to a verified OneCompany installation. It intentionally starts safe and raises autonomy only after evidence.

## Stage 0 - decide policy before connecting AI

Write down:

- GitHub repository/repositories in scope;
- default/protected branches;
- data that must never enter prompts/logs;
- additional AI spend cap;
- human-only actions;
- desired initial autonomy level (L1/L2 recommended);
- CI commands that define deterministic green;
- whether unattended execution is allowed at all.

Set `.onecompany/budget.json` before enabling actors.

## Stage 1 - bootstrap

From a OneCompany checkout:

```bash
python onecompany.py bootstrap --target /path/to/project
```

Merge conflicts intentionally; do not use `--force` as a substitute for reviewing existing project governance.

Set `.onecompany/config.json` project repository/default branch.

## Stage 2 - configure GitHub

Follow `docs/GITHUB-SETUP.md`:

- protect default branch/ruleset;
- require PRs for material changes;
- configure required deterministic checks;
- block force push/deletion;
- keep Actions token permissions minimal;
- choose merge method;
- keep auto-merge off until L3 is proven.

Run:

```bash
python onecompany.py audit-github
```

Understand every warning.

## Stage 3 - create deterministic project CI

OneCompany's own validation workflow does not replace your application's CI. Establish reproducible commands for format/lint/typecheck/tests/integration/migrations/build/security as appropriate. Record them in project docs/WU contracts and protect the corresponding checks.

## Stage 4 - configure workers

Use `docs/agent-setup/README.md` and the provider guide for every actor you own.

For each actor:

1. install/connect the intended surface;
2. authenticate without committing secrets;
3. grant minimum repository permissions;
4. run read smoke;
5. run write/review/merge smoke only for capabilities you intend to route;
6. record non-secret results in `.onecompany/readiness.json`;
7. set `configured=true` and then `enabled=true` only when the intended route is genuinely usable.

You do **not** need every reference actor. A minimal safe company needs one implementer route, deterministic CI, and one independent review route (human review is acceptable initially).

## Stage 5 - configure roles/routing

Review `.onecompany/roles.json`, `.onecompany/actors.json`, and `.onecompany/readiness.json`.

Test the router:

```bash
python onecompany.py route --capability implementation
python onecompany.py route --capability code_review --for-independent-gate --exclude-author <actor-id>
```

If no eligible actor exists, that should fail visibly rather than invent capacity.

## Stage 6 - choose patterns/overlays

Review `.onecompany/patterns.json` and `.onecompany/overlays.json`. Keep core invariants. Select overlays per Work Unit only when useful; an overlay does not create a new worker.

## Stage 7 - Team Room / coordination

Create one durable GitHub Team Room issue if multiple workers need cross-stream coordination. Use `docs/COORDINATION-BUS.md`. Slack/Discord/Teams are attention layers only.

Do not turn heartbeats into work. Durable artifacts are progress.

## Stage 8 - first Work Unit

Create a low-risk WU from `.github/ISSUE_TEMPLATE/work-unit.md`.

- objective + non-goals;
- deterministic verification;
- risk/security/budget constraints;
- required capability;
- role overlay if useful;
- exactly one implementation lease;
- one canonical branch/PR.

## Stage 9 - prove the full loop

Follow `docs/FIRST-RUN-ACCEPTANCE.md`. Prove:

```text
lease -> implement -> CI -> independent exact-head review
-> stale-review invalidation -> failover -> expected-head merge
-> reconcile -> release lease
```

Do this before L3/L4.

## Stage 10 - optional unattended actors

Read `docs/UNATTENDED-AUTOMATION.md`. Templates live under `.onecompany/templates/` and are disabled/non-executable there.

Enable only after reviewing current provider docs and filling explicit version/cost guards. Generic unattended scout paths should start read-only.

## Stage 11 - no-idle / continuous operation

For L4:

- `no_idle.enabled=true`;
- ready-work dependencies are machine-readable;
- stale work is reconciled against live GitHub before failover;
- no idle-agent busywork;
- an eligible route exists or the system surfaces a genuine blocker.

A watchdog is shipped disabled. Turn it on only after runner/provider cost and notification behavior are understood.

## Stage 12 - incident/stop drill

Prove you can stop the company by disabling workflows/automations, revoking write credentials, disabling actors, and lowering autonomy. Review `docs/INCIDENT-RUNBOOK.md`.

## Final pre-autonomy command set

```bash
python onecompany.py doctor
python onecompany.py validate
python onecompany.py simulate
python onecompany.py readiness --local-probe
python onecompany.py audit-github
```

Then complete the adoption checklist and first-run acceptance evidence.
