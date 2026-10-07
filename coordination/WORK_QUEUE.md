# OneCompany Work Queue

`.onecompany/queue.json` is the approved machine planning authority. GitHub Issues and live PR/CI/review state are authoritative for live execution evidence. This file is a human-readable L5 mirror only and must never create or reorder Work Units independently.

Controller rule: use the repo-native canonical selector (including `scripts/next_work.py`) against the versioned machine baseline, then reconcile the selected WU against live `main`, PR, CI, review, and lease state. Issue-only follow-ups are not executable WUs until they are registered in the planning baseline.

## ACTIVE

_None._

## NEXT / CANONICAL READY

1. **WU-MISTRAL-RECOVERY-001 / #231** - recover Mistral model-edit evidence and complete a real bounded source+test qualification under the canonical recovery WU.

## BLOCKED / NON-EXECUTABLE BACKLOG

- **WU-CLOUD-MISTRAL-DEV-001 / #133** - BLOCKED in the machine baseline because PR #224 merged scaffold-only without the required model-authored source/tests and independent non-Mistral review; recovery #231 must complete first.
- **#256**, **#254**, and **#95** remain issue-level follow-ups only. They are not canonical executable Work Units unless/until separately registered in `.onecompany/queue.json`.
- Human-decision, spending, credential, legal, destructive-production, and unavailable-provider-capacity work is not production NEXT work.

## DONE / RECONCILED

- **#150 WU-P1-BRIEF-001** - main contains `scripts/product_brief.py`, `docs/PRODUCT-BRIEF.md`, and focused self-tests; issue closed completed.
- **#178 WU-P1-JOURNEY-001** - main contains `scripts/first_run_journey.py`, `docs/FIRST-RUN-JOURNEY.md`, and focused self-tests; issue closed completed.
- **#151 WU-P1-RUNTIME-001** - main contains `examples/vertical-slice/app.py`, `docs/VERTICAL-SLICE-RUNTIME.md`, and vertical-slice tests; issue closed completed.
- **#149 WU-P1-PREVIEW-001** - main contains Phase-1 preview/runtime evidence, preview tests, and Mission Control preview-readiness implementation; issue closed completed.

Snapshot refreshed: 2026-10-07.
