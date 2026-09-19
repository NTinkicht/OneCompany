# WU-PILOT-001 — A4/L2 live-pilot intake (preparation, not qualification)

Follows [PR #113](https://github.com/NTinkicht/OneCompany/pull/113)
and tracks [issue #114](https://github.com/NTinkicht/OneCompany/issues/114).
The product source remains **L1**. The intake script is read-only. Running it
never installs a workflow, spends money, creates an implementation lease,
dispatches an agent, approves review, merges, or verifies P1/P3. A successful
report is **not** a license to run an unfamiliar public repository.

## Pilot topology

Obtain separately authorized PUBLIC disposable GitHub repositories:

- A4-A: `<owner-a>/<scratch-a>`, initial test WU `WU-A`.
- A4-B: `<owner-b>/<scratch-b>`, initial test WU `WU-B`.
- L2-C: `<owner-c>/<scratch-c>`, separate WU `WU-C`, existing canonical
  PR and owner-published native implementation lease.

A4-A and A4-B **must have distinct owners**. All three repositories must be
distinct. Do not substitute OneCompany, Tabibi, Veritas-Atlas, or an existing
real project for a disposable pilot. An input `"disposable": true` is a
declared intention, **not** a cryptographic proof of ownership or consent.

Install the **reviewed OneCompany source tree** into each target's default
branch (do not execute source-repository workflows against the targets). Keep
the target's `.onecompany/config.json`, `queue.json`, `budget.json`,
`readiness.json`, `dispatch.json`, and `actors.json` project-local, with
exact repository identity, LOW-risk fixture write scope, verified actor capacity,
L2 target approval, stop=false, and zero-extra-spend/included runner policy.
Each target's base-trusted `config.project` must explicitly declare
`"disposable_pilot": true`; this prevents a manifest-only disposable claim
from passing against an ordinary production configuration. It does not
replace the actual repository owner's consent.
Never transplant source OneCompany queues, actors, leases, secrets, or authority
into another repository. P3 also needs an initialized target-local durable
ledger, an already created/assigned PR and corresponding native lease. This
cannot be faked by copying `.onecompany/state.json` or a chat message.

Install exact disabled workflow template contents under their corresponding
`.github/workflows/*.yml` paths. For the two A4 targets:

- `onecompany-a4-pr-producer.yml.disabled` ->
  `.github/workflows/onecompany-a4-pr-producer.yml`;
- `onecompany-a4-fixture-validation.yml.disabled` ->
  `.github/workflows/onecompany-a4-fixture-validation.yml`.

For L2-C, install **both A4 workflows and both L2 workflows**:

- `onecompany-l2-fixture-validation.yml.disabled` ->
  `.github/workflows/onecompany-l2-fixture-validation.yml`;
- `onecompany-l2-fixture-repair.yml.disabled` ->
  `.github/workflows/onecompany-l2-fixture-repair.yml`.

No workflow becomes enabled in the source repository simply by merging this WU.

## Read-only intake

From the clean, reviewed OneCompany checkout, prepare a local
`pilot-intake.json` (do not commit target operational records into OneCompany):

```json
{
  "a4_pilots": [
    {
      "repository": "<owner-a>/<scratch-a>",
      "base_sha": "<40-hex target default-branch SHA>",
      "wu": "WU-A",
      "actor": "fixture-bot",
      "disposable": true
    },
    {
      "repository": "<owner-b>/<scratch-b>",
      "base_sha": "<40-hex target default-branch SHA>",
      "wu": "WU-B",
      "actor": "fixture-bot",
      "disposable": true
    }
  ],
  "l2_pilot": {
    "repository": "<owner-c>/<scratch-c>",
    "base_sha": "<40-hex target default-branch SHA>",
    "wu": "WU-C",
    "actor": "fixture-bot",
    "disposable": true,
    "pr_number": 7
  }
}
```

Use actual WU IDs and L2 PR number from the target's *reviewed, base-trusted*
queue. Use a GitHub read-only token for precisely the three authorized targets;
keep it in the runner environment, never in the manifest or a model prompt.

```sh
GH_TOKEN=<read-only-token> python scripts/p123_pilot_intake.py pilot-intake.json
```

The intake confirms source SHA pins, two-owner and three-repository isolation,
true PUBLIC visibility, the target-local base-trusted disposable-pilot setting,
the exact live default-branch SHA, unchanged reviewed
worker/workflow blobs, target-local control documents and zero-spend policy,
and the P3 queue/PR/ledger *configuration*. It deliberately does **not** prove
GitHub App permissions, user consent, Actions variable settings, lease admission,
actual failed/passed CI, non-author review or merge.

It refuses if the source P3 qualifier pins an outdated worker (a regression
found immediately after PR #113), if target files drift, or if the target's
base moves. For details of a refusal, inspect the target locally; the CLI
suppresses untrusted GitHub/API bodies and secrets.

## Complete the real P1/P3 evidence after intake

1. Independently confirm target-owner L2 authorization, GitHub workflow
   variables, dispatcher and public runner eligibility in each target; no
   paid fallback or automatic top-up.
2. A4-A and A4-B: dispatch the existing `onecompany.a4-produce`
   repository event under each target's authorized dispatcher. Record
   immutable actual run IDs, exact base/head and check runs. Duplicate dispatch
   must reconcile the *same* branch/PR, not create a second.
3. Run `scripts/a4_qualify.py` against **both actual installations** with
   their real evidence manifest, as documented in
   `docs/P123-LIVE-QUALIFICATION.md`.
4. L2-C: use an independent pre-bound WU/PR and active native lease; dispatch
   the intentional failing exact-head fixture CI, followed by the authorized
   `onecompany-l2-fixture-repair` worker, followed by repaired exact-head CI.
   Obtain independent non-author exact-head review and a governed merge plus
   canonical owner-published MERGED event. Do **not** copy A4's pre-PR queue
   (`pr: null`) into the P3 trusted base.
5. Run the read-only `scripts/p123_qualify.py` against immutable run/job/log,
   review, PR and ledger evidence. It **still exits nonzero** for the complete
   campaign until the separate Grok App-token write proof exists. Never
   manufacture GitHub-hosted run logs or upgrade L1 from an intake report.

The current connected GitHub account did not establish two independently
authorized disposable owners, so this WU cannot honestly record P1/P3 as
live-qualified. Pilot target identity and owner decisions remain external
per-installation facts.
