# Migrating an Existing Project to OneCompany

Do not stop product development to rewrite the repository around OneCompany. Introduce the control plane incrementally.

## Phase 0 — Inventory

Document:

- default branch and branch protections;
- current CI commands/check names;
- issue/PR conventions;
- deployment environments;
- secrets and permission owners;
- available AI workers/subscriptions/local tools;
- monthly additional spend limit;
- sensitive data classes;
- irreversible/human-only operations.

## Phase 1 — Observe only (L0/L1)

Copy `.onecompany/`, docs/templates, and `scripts/validate.py`. Keep all actors write-disabled. Create WUs for new work but retain existing human workflow.

Goal: learn whether the state/queue/contracts describe reality.

## Phase 2 — Autonomous bounded implementation (L2)

Enable one or more write-capable actors. Require explicit implementation leases and human merge. Start with low/medium-risk WUs.

Goal: prove single-stream implementation and deterministic remediation.

## Phase 3 — Independent exact-head gates (L3)

Connect an independent reviewer and enforce exact-SHA final verdicts plus expected-head merge. Automate merge only after repeated successful drills.

Goal: prove separation of powers.

## Phase 4 — Continuous queue (L4)

Model dependencies well enough that the orchestrator can safely choose the next ready WU. Enable no-idle detection.

Goal: remove the need for a human to prompt “continue” after every merge.

## Phase 5 — Governed autonomous company (L5)

Add maintenance/regression/incident queues, robust state reconciliation, capacity/budget failover, and operational metrics. Keep human-only decisions explicit.

## Avoid these migration mistakes

- enabling autonomous merge before CI/review contracts exist;
- giving every agent write/admin permission;
- copying another project’s secrets or stale state;
- importing giant historical backlogs as “ready” WUs;
- treating chat memory as source of truth;
- switching all workflows at once;
- running high-frequency scheduled watchdogs in a private repo without checking Actions cost.

## Definition of migrated

A project is meaningfully using OneCompany when a new contributor/agent can answer from the repository alone:

- what is being worked on;
- who/what owns the canonical implementation stream;
- what “done” means;
- what CI must pass;
- who can independently gate it;
- what the budget permits;
- what requires a human;
- what happens if the current worker fails.
