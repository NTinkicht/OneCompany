# L5 Activation Evidence - 2026-10-03

This file records the final activation evidence for the transition from `LIVE_SAFE` to `ACTIVE`.

## Protected-main control plane

- Reviewed control-plane commit: `88d2c6632543d937add00e1e9da493a260638057`
- Activation PR head is required to remain exact and current until merge.
- The activation changes only the shared control-plane manifest and this evidence record.

## Candidate verification

The post-Claude cutover candidate passed the following exact-head workflows before merge to protected `main`:

- OneCompany Validate
- L5 Hostile Controller Candidate CI
- L5 Activation Candidate CI
- L5 Cross-Repo Continuity Supervision
- OneCompany Handoff Supervision
- OneCompany Ledger Read Smoke

The activation PR must additionally pass the repository's current required `validate` status and independent exact-head review before merge.

## Platform enforcement

Live repository rulesets were re-read before activation. OneCompany, Tabibi and veritas-atlas have active default-branch rulesets enforcing pull-request flow, strict required status checks, one approving review, stale-review dismissal, review-thread resolution, 75% code coverage, deletion/non-fast-forward protection and no bypass actors.

## Governance clearance

Repository owner approval for final activation is recorded in issue #277. The installed enforcement policy is accepted and the main-changing governance freeze is cleared for this activation only. This does not authorize weakening any branch protection, status check, review requirement, coverage threshold, emergency stop or trust boundary.

## Activation invariants

Activation remains fail closed. Merge is permitted only if the exact current PR head has required CI, independent review, no unresolved review threads, current base/head evidence and the protected ruleset still matches the accepted enforcement policy.
