# OneCompany Work Queue

`.onecompany/queue.json` is the approved machine planning authority. GitHub Issues and live PR/CI/review state are authoritative for live execution evidence. This file is a human-readable L5 reconciliation mirror only and must never create, promote, block, or reorder Work Units independently.

Controller rule: use the repo-native canonical selector, including `scripts/next_work.py`, against the versioned machine baseline. Then reconcile the selected WU against live `main`, PR, CI, review, qualification, and lease evidence. A merged PR does not imply qualification completion when the canonical acceptance evidence is absent.

## ACTIVE

_None._

## CANONICAL READY / RECONCILE THROUGH NATIVE SELECTOR

- **WU-CLOUD-MISTRAL-DEV-001 / #133** - remains `READY` in the machine baseline as required by the existing qualification state machine. PR #224 is merged but does not by itself prove Mistral developer qualification.
- **WU-MISTRAL-RECOVERY-001 / #231** - canonical recovery WU for the scaffold-only #224 incident and missing model-authored source/test plus independent-review evidence.

The executable order is determined by the canonical machine baseline and native selector, not by the order of bullets in this mirror.

## NON-CANONICAL ISSUE BACKLOG

- **#256**, **#254**, and **#95** are issue-level follow-ups only. They are not executable Work Units unless separately registered in the approved planning baseline.
- Human-decision, spending, credential, legal, destructive-production, and unavailable-provider-capacity work is not production NEXT work.

## DONE / RECONCILED

- **#150 WU-P1-BRIEF-001** - main contains `scripts/product_brief.py`, `docs/PRODUCT-BRIEF.md`, and focused self-tests; issue closed completed.
- **#178 WU-P1-JOURNEY-001** - main contains `scripts/first_run_journey.py`, `docs/FIRST-RUN-JOURNEY.md`, and focused self-tests; issue closed completed.
- **#151 WU-P1-RUNTIME-001** - main contains `examples/vertical-slice/app.py`, `docs/VERTICAL-SLICE-RUNTIME.md`, and vertical-slice tests; issue closed completed.
- **#149 WU-P1-PREVIEW-001** - main contains Phase-1 preview/runtime evidence, preview tests, and Mission Control preview-readiness implementation; issue closed completed.

Snapshot refreshed: 2026-10-07.
