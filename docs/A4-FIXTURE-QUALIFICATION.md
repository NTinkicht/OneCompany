# A4a — dormant unattended fixture-only writer

This is a **project-independent qualification harness**, not a CompanyOS
rollout or an active worker. The installed OneCompany repository stays at L1.
The workflow is deliberately stored as a `.disabled` template and is not
copied into an active GitHub Actions workflow by ordinary bootstrap.

## What this stage can prove

For a separately owner-authorized, disposable project, a pre-existing
**LOW-risk** Work Unit with an exact `docs/onecompany-fixture/WU-....md`
write scope, bound branch/PR and durable active implementation lease can be
triggered by `repository_dispatch` without an interactive assistant.
The GitHub-hosted worker verifies the project's L2+ policy and exact lease,
actor readiness, route, budget, emergency stop, repository identity, protected
PR base, live PR head, branch and scope; it creates **one deterministic file**
on the same existing PR. Normal fast-forward push rejects a moved branch.
Repeated dispatch after an identical fixture is present creates no new edit.

It cannot create the first PR or acquire the first lease, mutate any
application logic, access providers outside GitHub, review its own PR, merge,
modify policy or workflows, apply database schema, deploy, or enable paid
capacity. This is an **A4a existing-PR updater**, not yet Issue #90's complete
unattended PR producer. A4b must resolve protected-base pre-PR reservation,
event-triggered PR creation, durable claim replay and isolated qualification.

## Preparation in a disposable project only

1. Have the project owner confirm the repo is disposable, can use included
   Actions minutes, and has the necessary GitHub branch/ruleset permissions.
   No workflow should use a personal access token or shared account secret.
2. Separately approve L2 on *that isolated project*. Document why the source
   OneCompany and any other installed projects stay at their prior level.
3. Create one LOW-risk fixture WU in its protected queue, map its exact
   canonical `branch` and `pr`, specify a one-path `write_scope`, and
   acquire a durable implementation lease under an independently verified,
   unattended GitHub Actions actor with zero-extra-spend capacity.
4. Verify the GitHub-hosted worker identity and that repository-scoped
   `GITHUB_TOKEN` has `contents: write`, `issues: read` and
   `pull-requests: read`; confirm repository owner controls who can trigger
   the typed event. A forked PR or differing repo identity is rejected.
5. Copy
   `.onecompany/templates/workflows/onecompany-a4-fixture-pr.yml.disabled`
   to `.github/workflows/onecompany-a4-fixture-pr.yml` **in that project only**
   through normal review. Set its GitHub Actions repository variable
   `ONECOMPANY_A4_FIXTURE_ENABLED=true` only after the checks above.
6. Trigger `repository_dispatch` with event type
   `onecompany.fixture-pr` and payload `work_unit`, `actor`, `lease_id`.
   A `workflow_dispatch` trigger is also available for initial manual
   testing; that alone does **not** qualify unattended operation.
7. Check the same PR's exact new head, committed fixture and project CI,
   then independent review. Duplicate event, stale head/base, foreign repo,
   unauthorised L1, wrong branch/PR, stop, expired lease, unavailable actor,
   missing capacity, non-fast-forward push and failed ledger/journal evidence
   must block or safely reconcile. Count **verified PR updates**, not starts.
8. Disable the variable/workflow, lower autonomy or revoke credentials to
   stop this pilot. No production rollout or L3/L4 follows automatically.

## Boundary of this PR

The tests exercise preflight, sandboxed path identity, scope, policy and
stale-head/base checks without writing to GitHub. Actual unattended write
qualification requires a separate disposable-repository run and exact
non-secret evidence from GitHub; source-level green CI is not that evidence.
Do not mark any actor `unattended.verified=true` solely because the module or
template exists.
