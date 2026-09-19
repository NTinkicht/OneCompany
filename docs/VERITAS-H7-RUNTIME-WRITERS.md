# Veritas H7 — current runtime-writer boundary (19 September 2026)

The machine-readable, exact-target-state writer inventory for H7 is
[`evidence/veritas/h7-runtime-writer-inventory.json`](../evidence/veritas/h7-runtime-writer-inventory.json).

The earlier 18 September onboarding observed Veritas main at
`e19a0780ec8d5237d923f6d1cdb3a4af24346c95`, before any of its new
deployment infrastructure existed. Do not apply that older Render/Neon absence
finding to the current repository.

At Veritas main `a0cd9230b68b7a5b4fd6c9392b9f748afb49bfb0`:

- Render's explicitly selected workspace contains a web API and a static site,
  deployed from `47bd085cb5e75d4b72acffc7a9e1e54300a61977`, with
  auto-deploy disabled.
- The dedicated Neon **Veritas Atlas Staging** project contains the owner-
  authorized initial application schema (14 public base tables including the
  EF history table, two EF migration IDs). Project HUMAN is not this database.
- PR #5 created the review-only migration script; PR #6 merged the staging
  external HTTP smoke workflow. Neither justifies an assumption that other
  external writers are absent.
- GitHub deployment/environment/hooks, other hosts/accounts, manual scripts,
  complete migration-writer roster, and rollback controls still require
  target-specific inspection.

**H7 remains blocked.** This document is evidence, not approval for
CompanyOS cutover, autonomous merges, additional migration, deployment,
budget expansion, or credential changes. The complete activation plan is
[Veritas activation](VERITAS-ACTIVATION.md) and
[OneCompany issue #87](https://github.com/NTinkicht/OneCompany/issues/87).
