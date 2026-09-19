# Veritas Atlas activation checkpoint — 19 September 2026

**Purpose:** put current target reality back into OneCompany, not to declare a
cutover. Companion exact-target evidence:
`source-evidence/veritas-atlas/staging-runtime-2026-09-19.json`.
Prior C1/C2a snapshots observed the target on 18 September at
`e19a0780...` and are historical, not the live decision boundary.

## What is operating now

- Veritas main: `31d03e3b73fd79d99afc943b8be348a1985f892d` (PR #5 merged).
- Render API and canonical Vite static site both report live from
  `47bd085cb5e75d4b72acffc7a9e1e54300a61977`; auto deploy is OFF.
  A later code merge is not necessarily a new production deployment.
- Dedicated Neon `Veritas Atlas Staging` PostgreSQL database has zero
  application tables as observed via its own connected account.
- CI produced a review-only idempotent EF migration artifact at
  [run 35429346453](https://github.com/NTinkicht/veritas-atlas/actions/runs/35429346453),
  SQL SHA-256 `350f62749a168d5d41b72764b6a22994ef18973ce9b02c064f0999efa584f298`.
  Artifact generation and PR approval did **not** apply that SQL.
- No independent HTTP, authenticated login or DB-backed functional smoke
  response has been captured. Render `live` is not proof of user readiness.
- The originally entered Neon/bootstrap secrets appeared in a chat. Rotate
  both privately before using real data; no replacement credentials belong
  in this report, issue comments or git history.

## Why Kaporal was involved so often

Two distinct boundaries have been conflated:

1. **Fix/work loop:** a worker can diagnose a red CI step, edit the existing
   canonical PR, rerun and recheck CI without escalating every attempt.
2. **Promotion/release gate:** the current L1/L2 and target GitHub policy
   preserve independent human approval/final merge. AI review remains
   advisory; it is never falsely represented as a human Code Owner.

Never create a fresh PR merely because a CI fix is needed on the same Work
Unit. Promote the **final exact head** after all corrections, not every
intermediate commit.

## Operational activation sequence

**A. Reconcile without target mutations.** Refresh target main SHA, open PRs,
protected-main/ruleset evidence, build/CI, Render deploy/autoDeploy, Neon
schema, external scheduled/human writers and recovery owners. Update C1/C2a
with this new observation boundary; preserve all unresolved findings and
separate OneCompany authority. Do not flip H1–H8 simply because a service is
live.

**B. Finish staging establishment.** Independently inspect the SQL artifact,
rotate exposed bootstrap and database-role secrets privately, obtain the
owner's separate go/no-go for the first migration, record migration versions
and non-destructive DB smoke, verify actual web/API and auth flows. Include
first-deploy rollback with the two specific Render service IDs, schema
compatibility and operator. Fix the documented dependency advisories
through one coherent reviewed security work unit.

**C. Verify target promotion protection.** Require protected `main` and
exact-head CI at the GitHub administrative level, reviewer independence
and no bot-as-human substitution. H1 remains unverified until the GitHub
settings are evidenced. Runtime writer inventory H7 and release contract H8
must be target-specific and current.

**D. Obtain scoped cutover.** Only after reviewed H1–H8 evidence, fresh
shadow adoption and exact-boundary C2b approval should OneCompany install
its scoped control plane into Veritas, import bounded work units and acquire
leases. This checkpoint alone grants no such authority.

**E. Advance autonomy in evidence-backed stages.** OneCompany integration
currently says `L1`; its only verified unattended worker is read-only.
Qualify a real unattended *implementation* route before promising hands-free
24/7 coding. Prove lease races, independent exact-head checks, expected-head
merge, emergency stop, no paid fallbacks and recovery in a disposable scope.
An explicit human decision raises L2/L3 authority once the policy and
drills actually permit it. At L3, ordinary scoped product changes can follow
a delegated independent machine-gate/merge route; high-risk migrations,
governance, credentials, budgets, policy changes and exceptional releases
retain their designated human decision gates.

## Current authority

This is observation and planning **only**. The authoritative
`v-harden-gates.json` remains blocked. A successful Veritas PR or Render
deployment does not transition that file. The OneCompany trusted base,
human sovereignty, zero-extra-spend policy and emergency stop are unchanged.
