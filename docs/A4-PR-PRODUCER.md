# A4 single-PR factory qualification — priorities 1–4

This work unit lives in **one source PR (#102)**. OneCompany remains a reusable
product: the source repo is L1; no target is implicitly installed or promoted.
This PR does not itself provide proof of a real unattended production run.

## 1. Reconcile before selecting new work

- The already merged planning WU-PFC-001 (Issue #8 / PR #9) is DONE in the
  machine-readable queue, rather than blocking next-work forever.
- WU-A4-FACTORY-001 is the canonical current OneCompany work stream (#90,
  PR #102), and its portfolio/requirement links use the approved baseline.
- The changelog distinguishes **unreleased** work from the VERSION=0.3.0
  published identifier. A new product release must be cut independently.
- Issue #95 remains open for full durable-claim/PR-intake semantics beyond the
  narrow disposable pilot; source repository CI is not live qualification.

## 2. Atomic first-branch reservation and recovery

The proposed `a4_pr_producer.py` is an opt-in, fixture-only project-local
worker. An explicitly approved L2 disposable installation, verified actor and
event dispatcher may submit `repository_dispatch` event
`onecompany.a4-produce` with `{"work_unit":"WU-A","actor":"fixture-bot"}`.

The worker validates GitHub run identity before any write and verifies the
checked-out default-branch SHA against live GitHub,
project identity, L2+ autonomy, stop state, complete zero-extra-spend
policy, verified included/free actor cost class, READY LOW-risk WU, a **single
deterministic branch** `onecompany-a4-wu-a`, absent PR mapping, exact fixture
scope, verified unattended actor and configured route. It creates an immutable
Git blob/tree/commit with fixture provenance and atomically creates the branch
ref with GitHub's create-ref API. Two races cannot both create that ref. A
duplicate/replayed event must verify the existing exact claim commit and the
sole live PR instead of branching again.

When PR creation returns an uncertain response, the job refuses further
mutation: a subsequent invocation first inventories the canonical PR. Foreign
branches, duplicate or closed PRs, a moved base, emergency stop or ambiguous
GitHub data fail closed. No arbitrary application edits or merge permission.

**Limit:** A Git ref reservation is not yet a durable ledger implementation
lease. The full #95 canonical start contract, atomic pre-PR durable claim,
offline/unknown API reconciliation and authorized failover need separate
qualification. This pilot only admits an exact single-file synthetic WU with
no dependencies and is not a general autonomous application producer.

## 3. Real unattended pilot (requires two disposable GitHub repositories)

The disabled template is
`.onecompany/templates/workflows/onecompany-a4-pr-producer.yml.disabled`.
For **each** disposable installation: use a **public disposable GitHub
repository** and verify public visibility in live GitHub metadata **before**
dispatch. Private or visibility-ambiguous repositories are not eligible: a
Python cost check executes too late to stop private runner billing. Both
installed workflows additionally use a job-level public-visibility guard,
evaluated before a hosted runner is allocated. Install the reviewed producer
template unchanged as `.github/workflows/onecompany-a4-pr-producer.yml` and
the approved CI template unchanged as
`.github/workflows/onecompany-a4-fixture-validation.yml` from
`.onecompany/templates/workflows/onecompany-a4-fixture-validation.yml.disabled`.
The qualifier pins this CI workflow's Git blob
`8480f5c8bd94187efe3ccb1effa9def51d15addd` and path; an arbitrary
manifest-selected always-green workflow is not valid. Approve project-local
L2, register and verify the least-privilege Actions actor and route, and
prepare an approved LOW-risk fixture WU with no PR number. Set the repository
variables `ONECOMPANY_A4_PRODUCER_ENABLED=true`,
`ONECOMPANY_A4_APPROVED_DISPATCHER=<authenticated GitHub login>` and
`ONECOMPANY_A4_LOGICAL_ACTOR=<project-local actor ID>`.

The worker token has repository-scoped `contents:write` and
`pull-requests:write`, with no deploy, database, workflow-edit or merge call.
Dispatch an authenticated `onecompany.a4-produce` repository event. Record
the Actions run ID, canonical branch, exact head/base and PR, plus the source
CI result. Send the same event again and verify no second branch/PR/commit.

**GitHub caveat:** Most ordinary push/pull-request events caused by the
repository's own `GITHUB_TOKEN` do not trigger a second Actions workflow.
Dispatch the approved `onecompany-a4-fixture-validation.yml` workflow with
`workflow_dispatch` on the canonical **fixture branch ref**; the resulting
run must attest the exact fixture head and check job `validate-fixture`.
Do not count a missing PR check as green and do not merge based on the
producer run alone.
The pilot's mechanism may finish creating a PR while CI/review awaits a
separate configured trigger.

## 4. Two real isolated installations

The source test `test_a4_first_pr_producer.py` simulates two separately
scoped GitHub installations and refusal cases. It is **not** live evidence.
For a real trial, create two independent disposable repositories, repeat the
event, collect non-secret manifests for both and run:

```bash
GH_TOKEN=<read-only-token> python scripts/a4_qualify.py pilot-manifest.json
```

The verifier also requires the immutable GitHub Actions job log to contain
exactly one `A4_PRODUCER_EVIDENCE:` JSON record printed by the approved
producer step. It must match repository, WU, actor, PR, branch, exact head/base,
run ID and run attempt. The run must refer to the expected producer workflow,
completed producer job/step and reviewed default-branch SHA, not an unrelated
successful dispatch. The verifier rejects a commit that modifies any path
besides the one fixture file, or two projects controlled by the same owner.
Source CI still does not qualify a live target installation.

Each manifest entry must contain `repository`, `work_unit`, `actor`,
`pr`, `head`, `base`, `workflow_run`, `check_name` (exactly
`validate-fixture`), `ci_workflow_run`, and `ci_workflow_path` (exactly
`.github/workflows/onecompany-a4-fixture-validation.yml`). The verifier
requires different repository owners, exact fixture/head/base, successful real
repository-dispatch run and a green GitHub Actions check on the exact PR
head, bound to its successful Actions run and the authorized validation
workflow path already present on the trusted base branch. Invoke the
validation workflow against the exact PR ref, not merely the default branch;
the check's verified Actions run must record the PR head SHA. Reviewer
independence and any later mechanical merge require separate evidence.
A source self-test, provider promise or scheduled ChatGPT task cannot
substitute for these two real runs.

### Stop and containment

Disable the repository variable, disable the target workflow or enable
the project emergency stop. Do not force-push away conflicting claims,
auto-delete a disputed branch, silently create a replacement WU or
resume an uncertain mutation without live reconciliation.
