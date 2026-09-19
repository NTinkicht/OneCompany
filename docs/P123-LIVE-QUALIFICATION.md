# P1–P3 one-PR convergence: disposable qualification, workforce, L2 pilot

This document records the reviewed *mechanisms* contributed together. It is
**not** a declaration that the source OneCompany installation has been promoted
from L1, that Grok can write, or that a real disposable installation has passed.
Keep live evidence in the owning installation. No extra paid provider, new Render
service, customer deployment or autonomous merge is enabled here.

## P1 — prove two real unattended first-PR runs

The existing A4 producer and `scripts/a4_qualify.py` perform the actual
single-canonical-branch/PR reservation and run-log-backed qualification.

For **two different owners** with independently authorized public disposable
repositories, install unchanged from the reviewed source:

- `.onecompany/templates/workflows/onecompany-a4-pr-producer.yml.disabled`
  as `.github/workflows/onecompany-a4-pr-producer.yml`.
- `.onecompany/templates/workflows/onecompany-a4-fixture-validation.yml.disabled`
  as `.github/workflows/onecompany-a4-fixture-validation.yml`.

Configure distinct local repository identity, budget and emergency stop; owner
approves L2 **for each disposable target**, verifies public visibility/included
runner capacity before dispatch, actor readiness, non-paid route, exact
LOW-risk fixture WU, and repository-scoped permissions. Source `main` stays
L1. Enable target variables for the producer and approved dispatcher/actor.
Deliver authenticated `onecompany.a4-produce` repository dispatch twice.
Confirm one exact branch, one PR, one commit, no speculative successor and no
unsafe retry. Trigger target fixture validation via workflow_dispatch on the
fixture head, not merely source CI. Collect real job/run IDs and execute:

```sh
GH_TOKEN=<read-only-repository-token> python scripts/a4_qualify.py a4-pilots.json
```

This verifier requires two distinct repository **owners** and the actual GitHub
job-log record; synthetic tests do not qualify P1.

## P2 — actual, independent multi-agent contribution

This PR also hardens Grok's existing default-OFF GitHub App writer against
unrequested token privileges and malformed nested repository and ref payloads.
It does **not** turn on a write MCP endpoint, assert token-level identity
from a Git commit author string, publish self-review, widen App installations,
enable unattended Grok, or add a manually required PR reviewer.

Before qualifying a Grok contribution, the existing writer must use the native
durable lease/authority kernel rather than the current conservative subset,
establish owner-bound OAuth write authorization, and pass the negative tests.
The owner-only App permission adjustment remains: select **only OneCompany**
for the App installation, then Content:write, PR:read, Issues:read; no
administration, actions, secrets, bypass, merges or other repos. A live
bot-authored bounded commit and exact-head CI on an existing assigned PR are
required. Grok the author cannot attest its own independent final review.

`scripts/p123_qualify.py` can OBSERVE a bot-attributed head but explicitly
returns `authenticated_app_write_verified: false`; GitHub commit author
association alone is not platform-token provenance. Do not upgrade readiness
or make deployment claims from it.

## P3 — intentionally fail CI, repair on SAME canonical PR, then merge

Install the **two additional disabled templates** in a *third, separately
authorized public disposable installation*, using a **separate pre-bound WU
and existing canonical PR**. Do not reuse an A4 producer's pre-PR queue
mapping for P3: the native merge kernel requires a PR-number mapping at the
trusted base. The target must already have a real authoritative
`ROLE_LEASE_ASSIGNED` admission for that WU/actor/PR and a live unexpired
implementation lease derived by the native durable ledger. The A4 source
producer, with its explicit `pr: null` preflight, is not a shortcut to that
state.

- `.onecompany/templates/workflows/onecompany-l2-fixture-validation.yml.disabled`
  as `.github/workflows/onecompany-l2-fixture-validation.yml`, unchanged;
- `.onecompany/templates/workflows/onecompany-l2-fixture-repair.yml.disabled`
  as `.github/workflows/onecompany-l2-fixture-repair.yml`, unchanged.

The validation workflow's reviewed Git blob is pinned in both worker and
verifier. Its initial A4 first-PR fixture **fails intentionally** because
`Repair: complete` is absent. It becomes green only after the bounded repair.
Record the failed run ID at the exact initial PR head.

To run the repair, in the project-local actor/dispatch/readiness records:
add the verified `ci_remediation` capability and a configured unattended
mechanism `github-actions-l2-fixture-repair`. The repaired WU's
base-trusted queue must bind the exact PR number; its native durable
`coordination_view(pr)` must show precisely one active admitted lease
matching WU, actor, branch, PR, exact base and initial head. The installed
repair workflow needs `contents: write`, `pull-requests: read`,
`actions: read`, and `issues: read` only. Confirm explicit owner opt-in
`ONECOMPANY_L2_FIXTURE_REPAIR_ENABLED=true`, the approved dispatcher, true
public repository eligibility, stop=false, zero-extra-spend baseline, trusted
default-branch checkout, the single READY LOW-risk WU, exact fixture scope and
reviewed validation workflow blob. `workflow_dispatch` the repair template
with work_unit, actor, canonical PR number, initial SHA and failed-run ID.

The reviewed worker:
1. Reads actual failed GitHub Actions run, checked-out/default branch,
   authoritative target policy and canonical first-PR claim.
2. Rejects foreign/stale/ambiguous refs, nonfailure CI, changed base, unrelated
   files, absent remediation capacity or unexpected client input.
3. Appends **only** `Repair: complete\n` to the exact fixture; uses one
   Git blob/tree/commit and a non-force branch ref update. It cannot merge.
4. Reads back exact PR/ref/content. A duplicate dispatch reconciles the same
   repaired SHA, never opens another PR or adds another repair commit.
   Revalidates the native durable lease and exact refs immediately before
   the non-force ref update.
5. After an uncertain ref response, fails without retrying a mutation.

Dispatch L2 validation on the repaired branch SHA; collect its successful run
and exact-head check. Obtain independent non-author review under the target's
existing policy, merge through the existing gated pathway and verify the
owner-published durable `MERGED` event. Do not allow a proposed bot reviewer
to sign its own work. No routine individually named approver is added.

A source-compatible read-only qualification campaign manifest is:

```json
{
  "a4_pilots": [
    {
      "repository": "disposable-owner-a/public-project",
      "wu": "WU-A", "actor": "fixture-bot", "pr_number": 1,
      "base_sha": "<exact-40-hex>", "run_id": 111,
      "check_name": "validate-fixture",
      "ci_workflow_path": ".github/workflows/onecompany-a4-fixture-validation.yml"
    },
    {
      "repository": "disposable-owner-b/public-project",
      "wu": "WU-B", "actor": "fixture-bot", "pr_number": 1,
      "base_sha": "<exact-40-hex>", "run_id": 222,
      "check_name": "validate-fixture",
      "ci_workflow_path": ".github/workflows/onecompany-a4-fixture-validation.yml"
    }
  ],
  "grok_worker": {
    "repository": "NTinkicht/OneCompany", "pr_number": 123,
    "head_sha": "<exact-bot-attributed-head>"
  },
  "l2_pilot": {
    "repository": "disposable-owner-c/public-project",
    "wu": "WU-C", "actor": "fixture-bot", "pr_number": 1,
    "base_sha": "<exact-base>", "initial_head": "<exact-initial>",
    "repaired_head": "<exact-repaired>", "failed_run_id": 333,
    "passed_run_id": 444, "review_id": 555
  }
}
```

The manifest is a *request to read live evidence*, not authority. Run:

```sh
GH_TOKEN=<read-only-repository-token> python scripts/p123_qualify.py campaign.json
```

The consolidated campaign CLI deliberately exits nonzero even after P1/P3
evidence is observed, because P2's App-token-level write verification is still
pending. Never use its report as a green promotion gate or merge authority.

Run the P3 native-verification portion from the **authorized disposable
target's clean default-branch checkout** with GitHub CLI available and
read-only `GH_TOKEN` for that target. The verifier uses the same
`platform_identity` reviewer/author mapping and the canonical
`ledger_lib`/coordination replay as the merge kernel. A different Git
checkout or an invalid ledger refuses, even if raw GitHub comments look
plausible.

P3 verification checks the same PR and exact two-commit lineage, one fixture
path, old failed and new successful workflow_dispatch plus GitHub Actions
check-run identities, independently submitted APPROVED review pinned to the
repaired SHA, GitHub merge SHA, and a distinct trusted publisher's v2 durable
MERGED event bound to the WU/head/base/merge SHA. A result observes evidence;
it does not grant merging, App credentials or autonomy. P2 remains pending
until an actual authenticated App-token contribution is verified separately.

### Refusal drills

Duplicate dispatch, lost PATCH response, stale base/head, deleted fork,
malformed payloads, unrelated path, cost/quota uncertainty, unavailable actor,
missing CI, false CI success, self-review, missing ledger merge, owner/tenant
cross-contamination and emergency stop must all fail closed.

### Scope boundaries

The A4 qualifier expects the original **one-commit** fixture; it cannot
qualify a branch that has since received the P3 repair. Preserve P1's immutable
proofs and use a separate P3 installation/WU for a simultaneously verifiable
campaign. The source repository remains project-neutral and cannot manufacture
two distinct GitHub owners, change GitHub App permissions, or manufacture real
Actions job logs by creating a test.
