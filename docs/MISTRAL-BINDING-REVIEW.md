# Mistral's independent binding technical PR review

OneCompany delegates real PASS/FAIL **technical review** to Mistral Vibe.
Its protected-main `MISTRAL_REVIEW_V1` GitHub Actions workflow uses the existing
included entitlement with PAYG disabled; GitHub's trusted parent gives the
model no GitHub token and no file-reading tools, supplies a bounded one-shot
exact-head/base review packet, verifies CI and cumulative explicit non-Mistral
material authorship, then validates strict model JSON.

| Model verdict | GitHub platform event | Binding interpretation |
| --- | --- | --- |
| `NO_BLOCKING_FINDINGS` | `APPROVE` | PASS technical review, subject to all other merge gates |
| `CHANGES_REQUIRED` | `REQUEST_CHANGES` | FAIL; author must address findings and rerun |
| `INSUFFICIENT_EVIDENCE` / quota / invalid JSON / stale head | no approving review | Blocked, not PASS |

A bot login alone **never** grants review authority. The native
`scripts/platform_identity.py` validator requires a single exact-head/base
`ONECOMPANY_MISTRAL_BINDING_REVIEW_V1` marker in an APPROVED platform review,
published by `github-actions[bot]` during the completed successful
owner-triggered `onecompany-mistral-exact-head-review.yml` workflow running
on protected-main history and within that run's time interval. Only then may
it map to actor `mistral-vibe` with authority **code_review only**.
This is not a blanket approval identity for other Actions workflows and does
not grant root, spending, merge_execution, branch creation, or self-review.

The native gate still verifies non-self cumulative authorship, correct
exact head **and** base, scope, required CI, assurance packet, emergency stop
and platform `APPROVED` review; a Vibe review is not permission to ignore
any of those checks. A PR with Mistral-authored code must be reviewed by a
different qualified actor.

Existing PR #220 received real **advisory** Vibe review in
[run 36152811616](https://github.com/NTinkicht/OneCompany/actions/runs/36152811616);
its old `COMMENTED` platform review does **not** retroactively count as
binding PASS. After this PR is independently reviewed/merged, run a fresh
owner-authenticated exact-head review and prove an actual GitHub APPROVED or
CHANGES_REQUESTED state and the specific run provenance before claiming
binding deployment. No paid fallback or subscription-quota evasion.
