# Bootstrap OneCompany

This guide takes a repository from ordinary GitHub project to governed autonomous company.

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
- desired autonomy level L0-L5.

For the safest first adoption, use L2: autonomous bounded implementation, human merge.

## 2. Install the control plane

Copy these paths into the target project:

```text
.onecompany/
agents/
company/
docs/                 # or selected OneCompany docs
scripts/doctor.py
scripts/validate.py
.github/PULL_REQUEST_TEMPLATE.md
.github/ISSUE_TEMPLATE/
.github/workflows/onecompany-validate.yml
```

Do **not** copy provider secrets, access tokens, user IDs, private prompts, or historical state from another project.

## 3. Configure the company

Edit `.onecompany/config.json`.

Minimum fields:

```json
{
  "schema_version": "1.0",
  "project": {
    "name": "MyProduct",
    "source_of_truth": "github",
    "default_branch": "main"
  },
  "autonomy": {
    "level": "L2",
    "continue_when_ready_work_exists": true
  },
  "delivery": {
    "single_canonical_stream": true,
    "require_exact_head_gate": true,
    "require_independent_non_author_review": true
  }
}
```

Then configure `.onecompany/budget.json` and `.onecompany/actors.json`.

## 4. Register actors by capability

An actor entry describes what the company may ask the worker to do. It is not a permanent job title.

Useful capabilities:

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
ui_design
ci_remediation
merge_execution
state_reconciliation
```

For each actor record:

- availability mode: interactive, unattended, GitHub-native, local;
- read/write scope;
- capabilities and preference weights;
- cost class: included, free_allowance, metered, forbidden;
- constraints such as quota windows;
- whether it may independently gate work it authored (normally false).

Avoid hard-coding “Model X is always the developer.” A capable actor may be routed differently as capacity changes.

## 5. Define deterministic CI

OneCompany treats CI as the technical referee. Your project must state the commands that mean “deterministically acceptable.” Examples:

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

Only declare checks the repository can reproduce. Never let an AI review substitute for a failing deterministic check.

## 6. Create the first Work Unit

A Work Unit (WU) is the smallest dependency-ready unit that can be implemented, verified, reviewed, and merged independently.

Every WU should contain:

- unique ID, e.g. `WU01`;
- objective;
- motivation/risk being closed;
- dependencies;
- in-scope and explicitly out-of-scope items;
- acceptance criteria;
- required tests;
- security/privacy constraints;
- budget restrictions;
- human decisions required;
- intended implementation capability;
- intended independent review capability.

Use `.github/ISSUE_TEMPLATE/work-unit.md`.

## 7. Grant exactly one implementation lease

A lease binds:

```text
work_unit → actor → branch → PR → start_head → scope
```

A valid lease prevents duplicate implementation. Other actors may research or review read-only if policy permits, but only the lease holder may modify the canonical implementation stream.

If the holder becomes unavailable, expire/release the lease and grant a **failover lease on the same branch/PR**.

## 8. Execute the delivery loop

For each WU:

1. Reconcile repository state.
2. Confirm dependencies are satisfied.
3. Confirm budget/capacity allows the chosen actor.
4. Grant one implementation lease.
5. Implement only the bounded scope.
6. Run CI on the exact head.
7. If CI fails, classify the failure before editing.
8. Remediate on the same branch.
9. When CI is green, assign a non-author reviewer.
10. Reviewer verifies the exact SHA and acceptance contract.
11. Resolve every configured-severity finding.
12. Obtain explicit exact-SHA `PASS — MERGE_READY` (or your equivalent machine-readable verdict).
13. Merge only if the current PR head still equals the gated SHA.
14. Close/reconcile the WU, release leases, and update state.
15. Immediately select the next dependency-ready WU if autonomy policy allows.

## 9. Set budget policy before unattended operation

A zero-extra-spend company should declare, for example:

```json
{
  "additional_monthly_ai_spend": 0,
  "allow_paid_fallback": false,
  "allow_overage": false,
  "allow_auto_topup": false,
  "allow_new_paid_vendor": false
}
```

When a preferred actor is quota-limited, the router must choose an allowed fallback or stop with a visible `CAPACITY_BLOCKED` state. It must never solve a quota problem by silently spending money.

## 10. Configure human-only decisions

Recommended human-only classes by default:

- changing financial/budget policy;
- adding credentials or granting broader repository permissions;
- production data deletion or irreversible migrations;
- publishing secrets or sensitive datasets;
- legal/compliance commitments;
- changing the company constitution or autonomy level upward;
- disabling required security/CI checks;
- merging known high-severity unresolved findings;
- purchasing services or accepting paid overage.

You may delegate some later, but delegation should be explicit and version-controlled.

## 11. Validate before going unattended

Run:

```bash
python scripts/doctor.py
python scripts/validate.py
```

Then execute the scenarios in `docs/SIMULATION.md`:

- implementer quota exhausted;
- reviewer is also material author;
- review targets an old SHA;
- CI red;
- two actors attempt same lease;
- paid fallback forbidden;
- ready work exists with no active lease;
- stale state disagrees with GitHub;
- untrusted PR content tries to alter operating instructions.

Do not call the company autonomous until those failures are handled predictably.

## 12. Increase autonomy gradually

Recommended progression:

```text
L1 for planning → L2 for bounded implementation → L3 for autonomous gate/merge → L4 for continuous queue → L5 only after incident drills and strong observability
```

Autonomy is a permission level, not a marketing label. Raise it when evidence justifies it.

## Next reading

- `company/CONSTITUTION.md`
- `docs/ARCHITECTURE.md`
- `docs/OPERATING-MODEL.md`
- `docs/WORK-UNITS.md`
- `docs/ROUTING-FAILOVER.md`
- `docs/REVIEW-GATES.md`
- `docs/BUDGET-CAPACITY.md`
- `docs/SECURITY.md`
- `docs/MIGRATION.md`
