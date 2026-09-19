# Veritas Atlas activation — current operator entrypoint

The September 18 C1/C2a snapshot is historical, **not** the current
deployment or cutover boundary.

## Verified progress on 19 September 2026

- OneCompany PR #86 merged the live-staging reconciliation into
  `epic-0.6-integration`; PR #83 merged the updated, still **blocked** H7
  external-writer inventory.
- Veritas PR #6 merged its credential-free external HTTP smoke; the isolated
  Veritas Neon schema is initialized (13 application tables plus EF history,
  two migration IDs), but an authenticated DB-backed end-to-end user flow
  has not been independently proven.
- Both Render services have auto-deploy off and still report their original
  first-deploy source SHA; GitHub merges do not deploy themselves.
- Veritas PR #7 proposes a distinct PostgreSQL readiness endpoint; it is
  not live or release-authorized merely because a PR exists.

## Authoritative workstream links

- [H7 current writer inventory](VERITAS-H7-RUNTIME-WRITERS.md) — unresolved
  scopes remain blocked.
- [H8 staging release/recovery runbook](VERITAS-H8-RELEASE-RUNBOOK.md) and
  [machine-readable H8 evidence](../evidence/veritas/h8-release-rollback-2026-09-19.json).
- [19 September initial live-staging snapshot](../source-evidence/veritas-atlas/staging-runtime-2026-09-19.json)
  — a time-bound pre-initialization record, not today's schema state.
- [OneCompany activation issue #87](https://github.com/NTinkicht/OneCompany/issues/87).

## Automation boundary

OneCompany still has `L1` configured and no verified unattended
**write-capable** implementation worker. H1–H8 are not auto-cleared by PR
reviews, Render reports or database changes. A target cutover requires a
fresh exact-state adoption reconciliation and explicitly scoped owner
authority. Ordinary CI fixes should stay on the same canonical PR and
only the final eligible head should receive consequential approval.
