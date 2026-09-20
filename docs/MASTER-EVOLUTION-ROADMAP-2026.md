# OneCompany: master evolution roadmap and Phase 0 handoff

**Directive date:** 2026-09-20. **Tracking WU:** #123 (WU-STRATEGY-001). **Product parent:** #92 and #36. **Inventory:** [versioned external capability register](../.onecompany/external-capability-register.json).

> ONE HUMAN. ONE COMPANY. A COMPLETE AI-POWERED SOFTWARE ORGANIZATION.

This document is a **planned product trajectory, not proof of deployment or permission to widen autonomy**. The register's 61 unique candidates cover all 11 groups of the owner directive, including repeat occurrences of Playwright, Temporal, and xyflow without double-installing them. No new provider is activated by this roadmap. The underlying trusted OneCompany planning, lease, ledger, Execution Core, evidence and exact-head/base governance remain authoritative.

## 0. Reconciled checkpoint and safe transition

Observed source-repository snapshot 2026-09-20: `main` at `8f92e0ed278b2c71e904e0021eb81229baf6499c`; no open source PR on inspection; #122 merged following live Pilot C recovery work. The native Execution Core exists in `docs/EXECUTION-CORE.md` and Epic 0.7 guidance. The legacy `.onecompany/queue.json` still reports `WU-A4-FACTORY-001` as IN_PROGRESS with #102 despite #102 being merged: **treat that as unreconciled, not as an active lease or a successful live L2 proof**. `.onecompany/state.json` is explicitly a cache. A real target's GitHub/Team Room lease, exact refs, E-stop and evidence must be freshly checked before dispatch. Open parent/follow-ups include #36, #92, #95, #105, and OpenViking #47.

| Existing work | Provisional classification | Action at transition |
|---|---|---|
| Native Execution Core / Epic 0.7 | COMPLETE THEN EXTEND | Keep RunKey, journal, guards, Completion Gate and existing runtime adapter; qualify worker/tool implementations within them, never start a second Execution Core. |
| A4/L2 portable factory, Pilot C and #36/#92 | COMPLETE THEN EXTEND | Preserve genuine historical successful/failed runs; reconcile live qualification per target, canonical PR/lease, and close stale queue/status only through the existing durable process. |
| Canonical WU-stream defect #95 | CONTINUE / ADAPT | Preserve admission guard; complete simultaneous-start, orphan, replay and duplicate-PR proof. |
| Grok writer #105 | ADAPT | Existing scoped, default-OFF work is retained; live bot writes need owner-approved App permissions, independently verified lease and actual smoke, not model declarations. |
| OpenViking #47 and Learning Plane #51 | CONTINUE / EXTEND | Reuse #47 as its specific assessment; add Supermemory and shared context contract without claiming both are necessary at runtime. |
| Existing first-run onboarding / requirements / planning | COMPLETE THEN EXTEND | Expose existing assessments as a guided user journey; preserve one canonical specification and planning truth. |
| Project- or provider-specific duplicate orchestrators | SUPERSEDE only after evidence | No blanket cancellation. Identify exact conflicting WU/branch/owner first, then record a durable supersession and retention of useful evidence. |

**Transition rule:** do not create a duplicate WU writer. Phase 0 documentation and dependency-independent design can proceed now; target-writing work requires a verified clean handoff. OneCompany source must remain free of any named target's live operational records. Never reuse Pilot C or other disposable evidence as production/customer qualification.

### Phase 0 legacy wind-down checkpoint (2026-09-20; WU-P0-RECONCILE-001 / #128)

This updates the provisional checkpoint above **without rewriting historical evidence**. Source PR #102 merged useful A4 factory code; source PR #122 merged recovery code. Pilot A PR #3, Pilot B PR #2 and Pilot C PR #9 were all verified **closed without merge**. Pilot C's original native implementation lease `88ac3910-759b-4247-90d9-d0dea6e54e70` has a matching owner-published [ROLE_LEASE_RELEASED](https://github.com/NTinkicht/onecompany-pilot-c/issues/1#issuecomment-5750297646) in the archived Team Room #1. C demonstrated a real same-PR bot repair and green repaired-head CI, but initial worker success, strict independent platform review and governed P3 merge were **not** established.

The source `WU-A4-FACTORY-001` queue item is `CANCELLED` as an **archived/superseded qualification campaign**, not `DONE` and not a claim that the merged implementation vanished. No old-pilot writer may be inferred from that item. The owner reported that the Pilot C repair opt-in was disabled; the available connector cannot independently read the target Actions variable, so the report is not represented as a fresh API verification. No new legacy pilot is required before the new trajectory.

## 1. Product outcome and simple first-time journey

A new person should be able to say “build this idea” or “connect this repository.” OneCompany assesses the project read-only, asks only consequential clarifications, drafts an editable Product Brief, shows proposed features/dependencies and acceptance criteria, and obtains bounded permission to proceed. It then configures **one eligible worker**, creates one canonical WU, runs the *actual application* where supported, tests what the person can see and use, records evidence and independent non-author review, merges eligible changes, offers a preview, and explains what happened and what comes next.

The default surface is **Welcome → Create/adopt → Discover → Proposed roadmap → Agent team → Build → Run/preview → Quality → Release → Mission Control**. Expose tokens, contexts, Kubernetes, memory backends, distributed messaging and API gateways only when the project needs them. Give users clear explanations and reversible choices; do not require them to understand leases, PR base SHAs or provider internals. Advanced/owner-only settings remain available with explicit boundaries.

Mission Control is a **projection**, never a second control plane. Show: goal, features, dependency graph, current canonical WUs, real agent identity/capability, progress vs activity, live head/base and tests, evidence, preview, release state, budget, blockers, and stop. Mark unknown/unverified as unknown; display model-suggested plans separately from approved execution.

## 2. Architectural seams to establish before optional infrastructure

```text
Human / Mission Control (guided UX; read projection)
  → existing trusted CompanyOS (policy, portfolio, WUs, leases, Team Room)
    → eligibility, approved budget, capability router
      → existing Execution Core + bounded AgentRuntimeAdapter/RunKey
        → worker / isolated workspace
        → optional derived MemoryProvider / ContextProvider
        → optional ModelEndpointProvider (inference != worker authority)
      → application runtime + build / DB / preview identity
      → OCES and UIAssuranceProvider (exact build + head/base + RunKey)
      → Evidence Registry → independent non-author review → authorized merge
      → owner-scoped deployment / observability → validated learning → next WU
```

Inspect current code before creating interfaces. Extension contracts are conceptual: `MemoryProvider`, `ContextProvider`, `ModelEndpointProvider`, `RuntimeCapabilityProvider`, `WorkspaceProvider`, `UIAssuranceProvider`, `TelemetryProvider`, `SkillProvider`, `DeploymentProvider`. Every response carries provenance, tenant/project scope, relevant exact revision, bounded cost/privacy, failure semantics, and **no authority by retrieval, event or model output**. A failed optional provider falls back to canonical native operation or refuses the affected optional feature without corrupting state. Device, preview port, DB migration and deployment target require resource locks.

## 3. Phase 0 — plan everything *now*

Deliverables for #123 and immediate successors:
1. Freeze/reconcile a current source+target state snapshot: source `main`, all relevant integration branches, open issues/PRs, queue, live ledger/leases, exact refs, worker capacity and evidence; record stale-cache exceptions explicitly.
2. Preserve owner's full inventory in the external capability register. Each candidate has an ID, affected component, existing overlap, preliminary adapter/pattern plan, provider contract, dependencies, target phase, cost, infrastructure, privacy, licensing status, acceptance proof and future Epic/WU. **Unverified license and feasibility stay visibly unverified.**
3. Produce user journey, requirements/specification and feature dependency schemas compatible with existing catalog/portfolio; separate draft proposals from authoritative approved plan.
4. Define boundary threat model: provider output injection, stale/misattributed evidence, cross-tenant data, wrong build/PR, duplicate writer, model self-escalation, unavailable CI/device, secret leakage, unbounded retry or spend, license obligations and prompt retention.
5. Define fixed end-to-end benchmark and objective phase gates; write explicit assessment work for all 61 candidates without activating them.
6. Promote reviewed planning records into the canonical portfolio/queue through the normal WU mechanism; validate uniqueness, backlinks and dependency DAG. Never mark proposed candidate assessments READY from this document alone.

### Phase 0 decisions and cost guardrails

No new automatic paid API, GPU, managed SaaS, Kubernetes cluster, hosted browser or device lab. `.onecompany/budget.json` currently sets additional monthly AI spend to USD 0 with no paid fallback or auto top-up. Included subscription access is not proof of an unattended API or worker route. Commercial and open-source compatibility must consider the **exact selected component and fork**, not the marketing label “open source.” Make or reject each adoption after measured proof of value; log rationale. The current OneCompany licensing/public-release decision remains owner-only (#2).

### Immediate executable planning WUs (proposed IDs, not yet admitted to queue)

| WU | Scope | Depends on | Acceptance |
|---|---|---|---|
| `WU-P0-RECONCILE-001` | Exact source/target branch, Pilot C, queue/ledger/lease and worker-capacity reconciliation | #123 | One authoritative snapshot; no synthetic L2 proof or duplicate writer. |
| `WU-P0-CONTRACTS-001` | Extension points, threat model, data/authority flows, register validation | #123 | Contracts reuse existing core, all 61 candidates trace, integration cannot grant authority. |
| `WU-P0-LICENSE-001` | Exact-version license, fork, NOTICE, dependency, network and commercial assessment | register | No adoption with UNKNOWN legal position; owner resolves legal commitments. |
| `WU-P0-BENCH-001` | Fixed new/adopt/bug/UI/security/outage/rollback evaluation fixtures | contracts | Deterministic evidence manifest, adversarial refusal tests and outcome measurements. |

## 4. Phase 1 — one complete user-to-product vertical slice

**Critical path:** trusted baseline/reconciliation → `WU-P1-FOUNDATIONS-001` (reuse current schema/RunKey/lease seams) → `WU-P1-DISCOVERY-001` (questions and Product Brief) → `WU-P1-RUNTIME-001` (run actual app, local sandbox/preview and DB fixture where relevant) → `WU-P1-QUALITY-001` (AC-traced CI/API/browser/security essentials) → `WU-P1-VERTICAL-001` (one real bounded canonical WU through evidence, independent review, eligible merge and preview) → `WU-P1-MISSION-001` (visible guided state). Mission Control UI work may run in parallel after projection contract. `WU-P1-PLAYWRIGHT-001` supplies deterministic browser smoke on a supported app, not a claim to test every platform. Source tests alone never substitute for a live app.

**Proposed Epic mapping:**
- `EPIC-EVOL-DISC`: `WU-P1-DISCOVERY-001`; reuse requirements catalog and review UX on new idea + existing repository.
- `EPIC-EVOL-HAR`: `WU-P1-FOUNDATIONS-001`; extend native execution adapter and resource/environment boundaries.
- `EPIC-EVOL-RUNTIME`: `WU-P1-RUNTIME-001`; new/adopt app bootstrap, run, DB connection/migration planning, local safe preview and cleanup.
- `EPIC-EVOL-QUAL`: `WU-P1-QUALITY-001`, `WU-P1-PLAYWRIGHT-001`; minimum useful tests, traceable evidence and independent review.
- `EPIC-EVOL-MISSION`: `WU-P1-MISSION-001`; new-user guidance and canonical read projection.
- `EPIC-EVOL-VERTICAL`: `WU-P1-VERTICAL-001`; same-PR implement→repair→verify→merge→preview full rehearsal on an isolated disposable application.

**Phase 1 readiness:** both fresh creation and existing-repo adoption are shown; one real app starts; AC-linked tests and browser smoke run where supported; independent exact-head/base review and an authorized merge are observed; preview is inspectable; stop, outage and recovery are tested; cross-target scope, spending and author identity remain correct. Permit dependency-independent Phase 2 experiments after relevant contracts are verified, without blocking basic usability.

## 5. Phase 2 — deliberate advanced integrations

| Epic/workstream | Planned WUs | Integration-specific proof |
|---|---|---|
| `EPIC-EVOL-MEM` | `WU-P2-MEM-001`, `WU-P2-SUPERMEMORY-001`, `WU-P2-OPENVIKING-001` (reuse #47) | Compare native, Supermemory, OpenViking and optional combined arrangement on same questions with L0/L1/L2, relevance, token/latency, provenance, tenant leakage and outage test. Canonical `.onecompany/knowledge` remains authoritative. |
| `EPIC-EVOL-INF` | `WU-P2-INF-001`, `WU-P2-LITELLM-001`, `WU-P2-KSERVE-001` | Model vs deployment identity, endpoint adapter, capacity/readiness, CPU/GPU/Kubernetes feasibility, total operating cost, worker-identity separation and zero-additional-spend pilot if feasible; reserve KServe WU even if capacity blocks deployment. |
| `EPIC-EVOL-UI` | `WU-P2-UI-001`, `WU-P2-ARTEMIS-001` | ARTEMIS subordinate to runtime assurance; exclusive Android device/emulator lock, build+RunKey trace, cleanup, screenshots/redaction, stale-evidence refusal, explicit Android availability and repeatable comparison to Playwright/Maestro. |
| `EPIC-EVOL-HAR` | `WU-P2-HAR-001` | Harness gap benchmark: structured tools, sandboxing, stale generation, long-run recovery, context compaction, checkpointing and worker portability. Borrow demonstrated capabilities, not competing orchestration. |
| `EPIC-EVOL-COM` | `WU-P2-COM-001` | A2A/skills/events, verifiable idempotent handoff and native-ledger authority. |
| `EPIC-EVOL-QUAL` | `WU-P2-QUALITY-001` | AC-to-test graph; mutation, API property/contract, security, accessibility, performance and LLM tests selected by actual app risk. |
| `EPIC-EVOL-PROD` | `WU-P2-PRODUCT-001` | Feature change impact, graph cycles/critical path, candidate-vs-authoritative state and cross-file code impact. |
| `EPIC-EVOL-DES` | `WU-P2-DESIGN-001` | Accessible design tokens, components and visual regression visible to user. |
| `EPIC-EVOL-OBS` | `WU-P2-OBS-001` | Tenant-scoped traces, cost/outcome telemetry and dashboard with safe degradation. |

Every candidate in the machine-readable register also gets its own `ASSESS-EXT-###` **planning task** mapped to the group WU; these are not 61 concurrently writable source WUs and must be batched by conflict/capacity. Defer actual installations when dependencies fail, but retain the explicit item and revisit trigger.

### Four protected future commitments

**KServe:** Phase 0 architecture/fork/license/CPU-GPU/Kubernetes/cost/network and simple-serving comparison. Phase 2 `WU-P2-KSERVE-001` smallest approved model endpoint pilot and fallback; nothing silently provisions paid compute. It is not a worker or a replacement for the capability router.

**OpenViking:** Phase 0 reuses #47 and documents `viking://` L0/L1/L2, project isolation and AGPL commercial/network implications. Phase 2 `WU-P2-OPENVIKING-001` benchmarks native retrieval plus Supermemory and OpenViking; no overlap installed by assumption.

**Supermemory:** Phase 0 assess fork/license and useful index of validated lessons; Phase 2 `WU-P2-SUPERMEMORY-001` proves provider-neutral semantic history retrieval and exact-source fallback; no authority or secrets in untrusted indexes.

**ARTEMIS:** Phase 0 assess generic runtime/device contracts; Phase 2 `WU-P2-ARTEMIS-001` proves mobile exploration against build-specific Playwright/Android baselines with device locks, RunKey and private-data handling. Never let a device agent decide merge or lease.

## 6. Phase 3 — company operations at scale

`EPIC-EVOL-OPS` / `WU-P3-OPS-001`: bounded dependency maintenance, GitOps release, incident detection/rollback, resilience drills and safe renewal. `EPIC-EVOL-PORTFOLIO` / `WU-P3-PORTFOLIO-001`: multiple isolated projects with independent queues, owner budgets, previews, models and release policies in one Mission Control. `EPIC-EVOL-LEARNING` / `WU-P3-LEARNING-001`: demonstrate that verified earlier defects are prevented on later projects, with candidate→validated→retired lifecycle and privacy-safe retrieval. Advanced Kubernetes/self-hosted inference operations extend, but never replace, Phase 2 endpoint contracts. These WUs stay visible in the Phase 0 roadmap.

## 7. Comprehensive evaluation, phase evidence and safety

Fix benchmark cases **before** selecting providers: new project, existing repo adoption, full-stack feature, bug, feature dependency change, UI regression, security remedy, API and DB migration, worker failover, provider outage, context compaction, preview/release/rollback, slow/flaky mobile device and controlled incident. Each manifest records exact source head/base, target revision, WU/RunKey/generation, app build, test plan, artifact hashes, authorship/reviewer identity, cost class, environment and failure reason.

Track first-run user effort; time to useful brief; correct feature/AC coverage; end-to-end outcome rate; build/run/preview success; defect escape; independent review findings; recovery; duplicate-writer incidence (target **zero**); stale-evidence acceptance (target **zero**); privacy leak/authority escalation (target **zero**); median/p95 latency, context tokens and actual total cost per *successful* user-visible result. Record baseline and uncertainty; do not invent improvements or claim Phase completion from a passing unit test. A phase transition needs immutable concrete evidence and a reviewable decision record, not a date.

**Invariant gate:** human sovereignty; owner-only spending, credentials, legal, protected governance and destructive production actions; one canonical WU stream; generation fencing; exact-head/base CI and independent non-author technical review; no Kaporal159 or named standing reviewer requirement for routine technical PRs; bounded budget, privacy/project isolation and emergency stop. The graphical app, inferred memory, hosted model, queue cache and agent messages must never grant authority.

## 8. Traceability and work-start protocol

The [register](../.onecompany/external-capability-register.json) is the coverage ledger for all candidates; issue #123 is the Phase 0 WU; existing #47 is the OpenViking evaluation. Proposed `WU-P*` and `ASSESS-EXT-*` IDs are **not** live leases, READY queue entries or a license to open duplicate PRs. Next reviewed planning increment should add validated portfolio entities, requirement AC links and admitted nonconflicting WUs using the existing schemas; preserve the original backlog history and consult GitHub live state every time.

**First executable vertical slice:** disposable new full-stack application, basic sign-inless CRUD flow and safe local database fixture; user describes intended capability; receive and edit brief; approve bounded WU; harness implements on one canonical PR; application starts; Playwright + essential API/security checks collect exact-build evidence; independent non-author review; authorized merge; human-visible preview; Mission Control reports evidence, elapsed time and next dependency-ready WU. No real patient, payment, credential or production data.

This is a continuity contract: future OneCompany workers should recover the strategic direction from **this committed roadmap, the register and issue #123**, not from chat memory.
