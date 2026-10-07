# OneCompany Work Queue

GitHub Issues and live PR/CI/review state are authoritative. This file is the canonical ordered backlog snapshot for L5 replenishment.

Controller rule: when there is no open production PR, take the first dependency-ready item in **NEXT**, verify it is not already satisfied on `main`, and implement it. If it is already satisfied, move/reconcile it under **DONE / RECONCILED** and continue to the next item in the same run.

## ACTIVE

_None._

## NEXT

1. **#256 - Allow non-secret scalar values in external review credential scanner**
2. **#254 - Harden Mistral exact-head review output contract**
3. **#95 - Kernel: reject duplicate canonical Work Unit PR streams**

## BLOCKED / INFRA FOLLOW-UP

- Human-decision, spending, credential, legal, destructive-production, and unavailable-provider-capacity work is not production NEXT work.

## DONE / RECONCILED

- **#150 WU-P1-BRIEF-001** - main contains `scripts/product_brief.py`, `docs/PRODUCT-BRIEF.md`, and focused self-tests.
- **#178 WU-P1-JOURNEY-001** - main contains `scripts/first_run_journey.py`, `docs/FIRST-RUN-JOURNEY.md`, and focused self-tests.
- **#151 WU-P1-RUNTIME-001** - main contains `examples/vertical-slice/app.py`, `docs/VERTICAL-SLICE-RUNTIME.md`, and vertical-slice tests.
- **#149 WU-P1-PREVIEW-001** - main contains Phase-1 preview/runtime evidence, preview tests, and Mission Control preview-readiness implementation.

Snapshot refreshed: 2026-10-07.
