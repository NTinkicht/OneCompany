# Tabibi C1 - Read-only onboarding and migration map

Status: C1 evidence artifact for OneCompany Epic 0.6 issue #66.

This document is intentionally produced **outside the Tabibi repository**. C1 does not install, edit, reconfigure, pause, replace, or otherwise mutate Tabibi. The purpose is to make C2 safe.

## 1. Snapshot and authority

Evidence snapshot used for this pass:

- Tabibi repository: `NTinkicht/Tabibi`.
- Default branch: `main`.
- `main` observed at `58711da234ba6a9cc91497e068049ed1f61d47bf` (`WU75: lock public discovery security contract (#289)`).
- Active product stream observed after that main snapshot: WU76 / PR #291, branch `wu76-material-eta-change-policy`, head `3fe9d043bf9657ec5cb0006e3afbc3f57c552f10`.
- Live GitHub facts outrank checked-in coordination cache for transient PR/CI/review/merge state.
- This report becomes stale as soon as Tabibi advances. C2 MUST repeat live reconciliation immediately before any mutation.

The current Tabibi `main` branch endpoint reports `protected=false` at this snapshot. Treat that as an evidence gap requiring explicit re-verification before C2 rather than as permission to weaken or bypass governance.

## 2. Existing strengths to preserve

Tabibi already contains many of the invariants OneCompany is intended to provide:

- GitHub is explicitly declared authoritative for engineering coordination.
- One canonical implementation stream per bounded WU.
- One implementer at a time per stream.
- Exact-head CI and independent non-author review expectations.
- Material authorship is used for self-gating prevention.
- Zero-extra-spend is explicit and broad: paid APIs, PAYG, overage, credits, Vertex/OpenRouter and automatic top-ups are forbidden.
- Failover is capability-aware and must reconcile live evidence before replacing healthy work.
- Slack is an attention/culture layer, not an authority source.
- Gemini Agent and Gemini Chat are retired identities; Gemini CLI is a distinct active actor.
- Mistral Vibe is constrained to included-plan capacity with PAYG disabled.

C2 should therefore be a **migration and convergence**, not a template overwrite.

## 3. Observed coordination drift

### 3.1 Live GitHub vs checked-in state

At the snapshot, `coordination/STATE.json` and `coordination/WORK_QUEUE.md` still describe a post-WU66 state with no current PR and `PRODUCT-CONTINUATION-002` ready for decomposition. Live GitHub has already advanced to WU76 / PR #291.

Implication: these files are useful durable/context inputs but cannot be imported as current transient authority. OneCompany onboarding must reconstruct transient state from live GitHub first and only then compare the checked-in coordination model.

### 3.2 Actor-model disagreement

`coordination/ACTOR_REGISTRY.json` and `coordination/STATE.json` describe six active actors:

- `chatgpt`
- `codex`
- `claude`
- `copilot`
- `gemini-cli`
- `mistral-vibe`

But binding `coordination/AUTONOMY_PROTOCOL.md` v5 still calls itself a four-actor protocol and lists only ChatGPT, Codex, Claude and Copilot as the active roster.

Implication: C2 must explicitly reconcile protocol versioning before `.onecompany/actors.json`, readiness or routing becomes authoritative. It is unsafe to silently choose either representation.

## 4. Workflow estate and provisional migration classification

These classifications are intentionally conservative. `preserve` means C2 must keep the capability initially. `map` means OneCompany should model the capability while the existing implementation remains active. `supersede-later` means replacement is possible only after proof and a controlled cutover. No workflow should be deleted during C1.

| Existing Tabibi surface | C1 classification | C2 intent |
| --- | --- | --- |
| `.github/workflows/ci.yml` | PRESERVE | Keep Tabibi deterministic product CI as project-specific evidence. OneCompany assurance may consume it; it must not replace it blindly. |
| `.github/workflows/claude.yml` | MAP / PRESERVE | Map provider capability/readiness and authorship constraints. Preserve until equivalent OneCompany dispatch is proven. |
| `.github/workflows/company-room-sync.yml` | MAP / SUPERSEDE-LATER | Map durable coordination behavior first. Do not run a second writer to the same coordination truth. |
| `.github/workflows/event-handoff-dispatcher.yml` | MAP / SUPERSEDE-LATER | This overlaps OneCompany B2. Preserve during coexistence; replace only through one atomic ownership cutover. |
| `.github/workflows/gemini-cli-wake.yml` | MAP / PRESERVE | Retain zero-billing guard/read-only semantics. Integrate as a capability-scoped dispatch route later. |
| `.github/workflows/mistral-vibe-wake.yml` | MAP / PRESERVE | Retain PAYG-disabled/read-only allowlist boundary. Integrate as a capability-scoped dispatch route later. |
| `.github/workflows/nightly-qa.yml` | PRESERVE | Project-specific QA is useful evidence and should remain unless a demonstrably equivalent replacement exists. |
| Slack onboard/ingest/mirror workflows | PRESERVE | Slack remains attention/culture only. Do not promote it into authority. |
| heartbeat/supervision workflows | MAP / SUPERSEDE-LATER | This overlaps OneCompany B3. Never run two mutation-capable supervisors for the same leases/work state. |
| Team Room issue / current GitHub coordination | PRESERVE -> MAP | Treat as legacy-but-authoritative input until a reviewed migration proves the OneCompany ledger can replay/match it. |
| `coordination/STATE.json` | MAP | Import structure/context only after live reconciliation; do not trust transient fields as current truth. |
| `coordination/WORK_QUEUE.md` | MAP | Convert approved backlog/contracts to OneCompany WUs, but reconcile against live issues/PRs first. |
| `coordination/ACTOR_REGISTRY.json` | MAP | Translate capabilities, cost classes and identity constraints after resolving four-vs-six actor protocol drift. |
| `coordination/AUTONOMY_PROTOCOL.md` | PRESERVE / RECONCILE | Human-reviewed policy remains binding until a deliberate successor policy is approved. |

## 5. Active scheduled-supervisor collision boundary

Tabibi currently has existing external scheduled supervisors actively maintaining the canonical product stream. C1 deliberately does not encode their private scheduler configuration into this public repository. The only architectural fact C2 needs is that **an active external supervision plane already exists**.

Therefore C2 has a hard no-dual-writer rule:

1. OneCompany may observe while existing supervisors remain active.
2. OneCompany may build a shadow reconciliation result, but must not acquire leases, create product branches, dispatch implementers, merge, fail over writers, or publish authoritative coordination events in Tabibi during shadow mode.
3. Before mutation capability is enabled, choose exactly one control-plane owner for each capability: scheduling, event handoff, lease ownership, failover, merge execution and durable event publication.
4. Existing supervisors are disabled/re-scoped only through an explicit owner-approved cutover step, never opportunistically from C1.
5. If coexistence cannot prove one canonical writer, C2 fails closed.

## 6. Proposed C2 staged cutover

### Stage C2.0 - fresh reconciliation

Immediately before any C2 change:

- re-read Tabibi `main` and every open PR;
- reconcile active WU, exact heads, CI/review state and material authorship;
- inspect current Team Room/lease state;
- re-read actor registry, autonomy protocol, state and work queue;
- inventory currently enabled repository and external supervisors;
- verify branch protection/rulesets using an administration-capable source;
- abort if there is an ambiguous canonical writer or unresolved current product transition.

### Stage C2.1 - shadow projection only

Create a migration branch only after C2.0. Install or generate `.onecompany` in a mode where:

- ledger mutation is disabled;
- dispatch mutation is disabled;
- supervision is observe-only;
- no product PR is created by OneCompany;
- live Tabibi GitHub + legacy Team Room remain authoritative;
- projected OneCompany state is compared against live/legacy state for drift.

Acceptance: repeated reconciliation yields the same current WU/PR/head/authorship/dependency state as live GitHub without changing Tabibi behavior.

### Stage C2.2 - policy/actor convergence

Resolve the four-vs-six actor mismatch through a reviewed policy decision. Then map:

- actor identities and capabilities;
- zero-extra-spend cost classes;
- readiness evidence;
- implementation/review independence;
- Gemini CLI and Mistral Vibe guarded unattended routes;
- retired identities.

Still no duplicate product dispatch.

### Stage C2.3 - one capability at a time

Migrate only one orchestration capability per reviewed change. Recommended order:

1. read-only status/reconciliation;
2. advisory next-work proposal;
3. event wake observation;
4. bounded non-authoritative Team Room signal;
5. only later, lease/dispatch mutation after proving the incumbent path is disabled or delegated.

Every step has explicit rollback to the prior Tabibi mechanism.

### Stage C2.4 - mutation ownership cutover

Only after shadow parity and owner approval:

- designate OneCompany or the legacy mechanism as the single writer for each mutation class;
- prevent duplicate scheduler/event execution by configuration, not convention;
- keep emergency stop and zero-spend sovereign;
- preserve exact-head independent review;
- run one bounded L2 proof WU with human final merge.

## 7. Rollback requirements

A C2 change is not acceptable unless rollback can restore the pre-cutover operating mode without reconstructing hidden state.

Minimum rollback evidence:

- previous workflow/control files remain recoverable by Git history;
- canonical Tabibi product branch/PR is not rewritten;
- existing Team Room history is preserved;
- no new paid dependency or external authority service is required;
- OneCompany derived state can be deleted and rebuilt from GitHub + reviewed policy;
- disabling OneCompany does not prevent Tabibi from continuing under the pre-existing coordination model.

## 8. C1 exit checklist

C1 can close when:

- [x] Tabibi was inspected without repository mutation.
- [x] Live-vs-cache drift was identified.
- [x] Actor/protocol drift was identified.
- [x] Existing workflow/control surfaces were inventoried at a migration level.
- [x] Preserve/map/supersede-later classifications were recorded.
- [x] Active-supervisor collision risk was explicitly modeled.
- [x] A no-dual-writer C2 cutover plan and rollback boundary were documented.
- [ ] Exact-head OneCompany CI is green for this document PR.
- [ ] CodeRabbit has no unresolved actionable review thread on the final head.

C1 completion does **not** authorize C2 mutation. C2 starts only from a new live Tabibi reconciliation because the scheduled supervisors may have advanced the product stream after this snapshot.
