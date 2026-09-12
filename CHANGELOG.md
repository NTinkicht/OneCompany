# Changelog

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
- JSON Schemas are now validated against every machine-readable root control-plane document.

### Human follow-ups
- software license remains an explicit owner decision before public release;
- default-branch protection/required-check configuration remains an owner/platform setup step.
