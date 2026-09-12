# Bootstrap OneCompany

This guide takes a repository from ordinary GitHub project to governed autonomous company. For the complete zero-to-running sequence, also use [`docs/SETUP-FROM-ZERO.md`](docs/SETUP-FROM-ZERO.md).

## 1. Decide the trust boundary first

Before connecting workers, decide what they may do. Do not start from “which models do I have?” Start from authority.

Record:

- repository/repositories in scope;
- branches workers may modify;
- whether workers can open PRs, push to existing branches, merge, edit issues, or trigger Actions;
- commands that define deterministic green CI;
- data classes that must never enter AI prompts or public logs;
- additional monthly AI spend allowed;
- actions requiring a human decision;
- desired autonomy level L0-L5;
- whether unattended execution is permitted at all.

For the safest first adoption, use L1/L2: assisted or autonomous bounded implementation with human merge.

## 2. Install the control plane

From a OneCompany checkout:

```bash
python onecompany.py bootstrap --target /path/to/your/project
```

The bootstrap copies the control plane, agent adapters, company/pattern/overlay docs, operational docs/scripts, root instruction entrypoints, GitHub templates, and the safe OneCompany validation workflow. It intentionally refuses to overwrite existing files by default.

Do **not** copy provider secrets, access tokens, user IDs, private prompts, or historical state from another project.

## 3. Configure project identity and budget

Edit `.onecompany/config.json` and `.onecompany/budget.json` first.

Minimum project identity:

```json
{
  "schema_version": "1.0",
  "project": {
    "name": "MyProduct",
    "repository": "OWNER/REPO",
    "source_of_truth": "github",
    "default_branch": "main"
  },
  "autonomy": {
    "level": "L2",
    "continue_when_ready_work_exists": false
  }
}
```

A zero-extra-spend policy should keep additional spend at `0`, paid fallback/overage/auto-top-up/new paid vendors disabled, and unknown cost behavior fail-closed.

## 4. Configure GitHub controls

Follow [`docs/GITHUB-SETUP.md`](docs/GITHUB-SETUP.md): protect the default branch, use PRs, configure deterministic checks, constrain Actions tokens, and review agent/app permissions.

When `gh` is authenticated:

```bash
python onecompany.py audit-github
```

The audit is read-only/advisory. Understand every warning before raising autonomy.

## 5. Register actors by potential capability

`.onecompany/actors.json` describes what an actor type can potentially do. It is not proof that your account/runtime is currently ready.

Common capabilities include:

```text
architecture
planning
implementation
repository_intelligence
regression_scouting
test_design
failure_analysis
code_review
security_review
documentation
research
ci_remediation
merge_execution
state_reconciliation
```

Avoid permanent statements such as “Model X is always the developer.” Roles belong to the project and routing changes as capability/capacity changes.

## 6. Configure and smoke-test every worker

This step is mandatory and was deliberately separated from actor declaration.

Read [`docs/agent-setup/README.md`](docs/agent-setup/README.md) plus the provider guide for each worker you intend to use.

For each actor:

1. install/connect the exact execution surface;
2. authenticate without committing credentials;
3. grant least privilege;
4. run a harmless repository read smoke;
5. separately smoke-test write/review/merge only if those capabilities will be routed;
6. record non-secret evidence in `.onecompany/readiness.json`;
7. set `configured=true` / `enabled=true` only when the intended route is actually usable.

Then inspect:

```bash
python onecompany.py readiness --local-probe
python onecompany.py validate
```

`actors.json` = potential. `readiness.json` = proven current route. This lets OneCompany represent “review quota exhausted while implementation still works” without disabling the entire provider.

## 7. Define deterministic product CI

OneCompany treats CI as the technical referee. Your project must state reproducible commands/checks such as:

```text
format check
lint
typecheck
unit tests
integration tests
migration-chain tests
browser/smoke tests
production build
dependency/security audit
```

The OneCompany validation workflow validates the **company control plane**; it does not replace application/product CI.

Never let an AI review substitute for a failing deterministic check.

## 8. Create the first Work Unit

A Work Unit (WU) is the smallest dependency-ready unit that can be implemented, verified, reviewed, and merged independently.

Every WU should contain:

- unique ID;
- objective and motivation/risk;
- dependencies;
- in-scope and non-goals;
- acceptance criteria;
- required tests;
- security/privacy constraints;
- budget restrictions;
- human decisions required;
- intended implementation/review capabilities;
- smallest useful role overlay set.

Use `.github/ISSUE_TEMPLATE/work-unit.md`.

## 9. Grant exactly one implementation lease

A lease binds:

```text
work_unit -> actor -> branch -> PR -> start_head -> scope
```

Other actors may work in orthogonal lanes, but only the active implementation lease holder materially modifies that canonical stream. If the holder fails, release/fail over the lease while preserving the same branch/PR/history.

## 10. Execute the delivery loop

For each WU:

1. Reconcile live repository state.
2. Confirm dependencies.
3. Confirm budget and capability-level readiness.
4. Grant one implementation lease.
5. Implement bounded scope.
6. Run deterministic CI on exact head.
7. Diagnose failures before editing.
8. Remediate on the same stream.
9. Route an eligible non-author reviewer.
10. Review the exact SHA and original evidence.
11. Resolve configured-severity findings.
12. Obtain explicit exact-head `PASS — MERGE_READY` (or configured equivalent).
13. Merge only if current head still equals the gated SHA.
14. Reconcile/close WU/release leases.
15. Select next dependency-ready WU only if autonomy policy allows.

## 11. Use a durable coordination bus when useful

For multi-actor work, create one GitHub Team Room issue and follow [`docs/COORDINATION-BUS.md`](docs/COORDINATION-BUS.md). Heartbeats are visibility, not progress. Slack/Discord/Teams remain optional attention layers.

## 12. Configure human-only decisions

Recommended human-only classes by default:

- changing budget/financial policy;
- adding/expanding credentials or repository permissions;
- production data deletion/destructive actions;
- irreversible migrations without tested recovery;
- legal/compliance/business commitments;
- raising autonomy level;
- disabling required security/CI checks;
- merging unresolved high-severity findings;
- publishing sensitive data;
- purchasing services/accepting overage.

Delegation may evolve, but it should be explicit/version-controlled.

## 13. Validate the company before unattended operation

Run:

```bash
python onecompany.py doctor
python onecompany.py validate
python onecompany.py simulate
python onecompany.py readiness --local-probe
python onecompany.py audit-github
```

Then complete [`docs/FIRST-RUN-ACCEPTANCE.md`](docs/FIRST-RUN-ACCEPTANCE.md) and the scenarios in [`docs/SIMULATION.md`](docs/SIMULATION.md), including quota failover, stale review, duplicate lease, forbidden paid fallback, stale state, prompt injection, and no-idle behavior.

## 14. Enable unattended paths only deliberately

Read [`docs/UNATTENDED-AUTOMATION.md`](docs/UNATTENDED-AUTOMATION.md). Reference provider workflows are stored under `.onecompany/templates/` with `.disabled` suffixes. Bootstrap does not activate them.

Before enabling any unattended route, verify current provider documentation, exact version, credential/cost class, trusted trigger, tool permissions, timeout, output redaction, and stop path.

Generic unattended scouting should start read-only/non-gating.

## 15. Increase autonomy gradually

Recommended progression:

```text
L1 planning/assistance
 -> L2 bounded autonomous implementation + human merge
 -> L3 autonomous delivery/gate/merge
 -> L4 continuous queue/no-idle
 -> L5 governed continuous company only after drills/observability/incident maturity
```

Autonomy is permission backed by evidence, not a marketing label.

## Next reading

- `docs/SETUP-FROM-ZERO.md`
- `docs/AGENT-CONFIGURATION-MATRIX.md`
- `docs/agent-setup/README.md`
- `docs/SECRETS-AND-PERMISSIONS.md`
- `docs/GITHUB-SETUP.md`
- `company/CONSTITUTION.md`
- `docs/OPERATING-MODEL.md`
- `docs/WORK-UNITS.md`
- `docs/ROUTING-FAILOVER.md`
- `docs/REVIEW-GATES.md`
- `docs/CONTEXT-ENGINEERING.md`
- `docs/UNATTENDED-AUTOMATION.md`
- `docs/FIRST-RUN-ACCEPTANCE.md`
- `docs/INCIDENT-RUNBOOK.md`
- `docs/TROUBLESHOOTING.md`
