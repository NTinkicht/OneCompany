# Changelog

## 0.3.0 — 2026-09-13

Planning, flow-control and Engineering Excellence release that turns OneCompany from a globally serialized autonomous-delivery loop into a governed **CompanyOS** with strategy-to-execution traceability and conflict-safe parallel work.

### Planning and portfolio model
- typed planning graph for Objective, Epic, Feature/Capability, optional User Story, formal Requirement, Acceptance Criterion, Work Unit and Release/Outcome;
- formal BR/UR/FR/NFR/SEC/DATA/OPS/UX/CON requirement classification remains independent from planning vocabulary;
- canonical versioned portfolio, requirements/acceptance-criteria and risk registers;
- deterministic confidence-weighted priority scoring, dependency graph and critical-path calculation;
- bidirectional planning/requirement-to-WU traceability validation;
- OneCompany dogfoods the model through `OBJ-001` / `EPIC-001` / `CAP-001` / `WU-PFC-001` mapped to Issue #8 and PR #9.

### Safe company-wide parallel execution
- one canonical implementation stream and active implementation lease **per Work Unit** rather than one stream for the whole company;
- bounded global WIP plus per-actor verified implementation capacity;
- hard dependency, declared write-scope, semantic resource-lock and risk-policy conflict checks;
- unknown scope fails closed to serialization and critical-risk work serializes by default;
- durable ledger races preserve first-valid canonical ownership while allowing disjoint WUs to coexist;
- merge/release/failover of one WU no longer destroys unrelated active streams.

### Exact integration evidence
- binding gates record exact candidate head SHA **and exact base SHA**;
- base movement after a parallel merge invalidates stale integration evidence;
- live PR changed files are checked against declared WU scope before merge-ready gating and again before merge;
- stream-scoped blockers and human decisions replace unsafe global-singleton assumptions;
- gate/merge resolution can derive the WU directly from versioned PR mapping.

### Engineering Excellence / OCES
- requirements-quality, architecture, traceability, risk, testing, documentation, security, UX, operations and release standards;
- risk-aware test families spanning static/unit/component/integration/contract/API/E2E/acceptance/regression/property/fuzz/mutation/security/migration/performance/reliability/accessibility/visual/compatibility/operations/AI evaluation as applicable;
- quantitative line/branch/changed-line/mutation profiles and exact-SHA evidence;
- canonical risk-register governance, including explicit human acceptance for critical residual risk;
- explicit, owned, expiring quality waivers; silent permanent suppressions forbidden.

### Autonomous planning and supervision
- planner can rank work, explain priority, compute a safe parallel set and expose critical path;
- reconciliation/status/supervision understand several active WU streams;
- no-idle now means **safe executable work + real eligible worker capacity + no lease**, not merely a READY label;
- supervisors may fill conflict-free WIP slots but remain liveness replicas rather than extra implementers;
- post-merge graph recomputation releases newly unblocked work.

### Modern adoption experience
- new read-only-first `onecompany onboard` command for new projects, existing repositories, GitHub-template copies and installed companies;
- stack, tests, CI, contracts and framework-path collisions are detected before mutation;
- `--apply` installs only after the assessment is safe; product-owned collisions are never silently overwritten;
- read-only assessment is regression-tested to produce no filesystem side effect;
- framework self-tests/reference assurance assets are namespaced under `.onecompany` so product `tests/` and `examples/` remain product-owned.

### Source-of-truth model
- versioned `.onecompany` graph = approved machine planning/policy baseline;
- GitHub Issues/Projects = human collaboration and visualization surface;
- GitHub branches/PRs/exact SHAs/changed files/Actions/reviews/merges = live execution evidence;
- Team Room ledger = durable coordination facts that should not mutate candidate heads;
- `.onecompany/state.json` remains derived cache only.

### Documentation and self-testing
- canonical Mermaid architecture flow in `docs/COMPANYOS-FLOW.md`;
- architecture, onboarding, scheduled-supervision, durable-ledger and failure-drill documentation aligned with parallel CompanyOS semantics;
- embedded self-tests for planning, ledger parallelism, scope guards, onboarding, assurance and risk acceptance;
- CI validates planning, risk register, flow/WIP/capacity, durable races, parallel simulation, supervision, bootstrap/init and Python compilation.

### Governance hardening
- new planning/quality/risk/traceability policies and behavior-bearing planning/assurance scripts are protected control-plane paths;
- candidate control-plane changes remain governed by the trusted base and cannot authorize themselves;
- protected control-plane changes retain the authorized-human merge boundary.

### Human-only release follow-ups
- software license remains an explicit owner legal decision before public release (Issue #2);
- default-branch protection/required-check configuration remains an owner/platform administration step (Issue #3).

## 0.1.0-foundation — 2026-09-13

Initial OneCompany operating-system foundation.

### Autonomous company control plane
- GitHub-source-of-truth constitution, bounded Work Units, single-stream leases and same-stream failover;
- cumulative material authorship, independent non-author exact-head gate and expected-head merge;
- capability/readiness/budget/routing/dispatch separation;
- durable Team Room ledger with race-safe canonical leases and gate/authorship staleness;
- deterministic READY-only dependency selection and queue-cycle validation;
- L0-L5 autonomy, no-idle semantics and emergency stop.

### 24/7 operation
- event-driven handoff model plus scheduled reconciliation;
- GitHub supervisor templates and four-staggered-hourly ChatGPT supervisor pattern;
- scheduler-health checks, observe-only defaults and deterministic supervision simulation;
- supervisors cannot create duplicate implementation streams.

### Safety and governance
- no self-escalation constitution;
- candidate control-plane changes are proposals until trusted human/default-branch promotion;
- human merge boundary for protected control-plane changes;
- zero-extra-spend safe default and capacity circuit breaker;
- supply-chain audit for immutable Action pins, no managed `pull_request_target`, no `write-all`;
- idempotency, bounded retry, rollback/compensation and incident-containment requirements.

### Quality and product experience
- PRODUCT, ARCHITECTURE, SECURITY, QUALITY, DESIGN and OPERATIONS starter contracts;
- framework-neutral UI design-system, accessibility, responsive, localization/RTL, visual-regression and performance guidance;
- expanded WU/PR evidence contracts and specialist role overlays.

### Setup and self-testing
- provider setup guides for ChatGPT, Codex, Claude, Copilot, Gemini CLI, Mistral Vibe, human and custom/local workers;
- safe `bootstrap` for existing repositories and one-time `init` for GitHub-template copies;
- `status`, `doctor`, `check`, schema validation and GitHub configuration audit;
- deterministic core/ledger/supervision simulations and bootstrap/init smoke tests;
- JSON Schemas are validated against every machine-readable root control-plane document.

### Human follow-ups
- software license remains an explicit owner decision before public release;
- default-branch protection/required-check configuration remains an owner/platform setup step.
