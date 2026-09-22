# Phase 1 — honest local evidence to Mission Control

The current first-run path has **real components**, but no one-shot full CompanyOS
execution: `onboard` / `brief` / `journey` → read-only proposed plan →
`demo` (disposable real HTTP checklist) → clean-checkout local quality smoke →
**this composer** → existing loopback Mission Control dashboard.

Rather than hand-editing a success-looking dashboard, this work unit connects
the already merged producers. From a OneCompany **source checkout**:

```bash
python onecompany.py journey --target /tmp/your-safe-project \
  --repository NTinkicht/your-safe-project --brief /tmp/owner-brief.json \
  --json > /tmp/journey.json

python onecompany.py demo --target /tmp/your-safe-project \
  --repository NTinkicht/your-safe-project --brief /tmp/owner-brief.json \
  --head <ACTUAL_CHECKOUT_HEAD_SHA> --base <ACTUAL_BASE_SHA> > /tmp/local-smoke.json

# From a CLEAN OneCompany checkout; refuse dirty or mismatched HEAD.
python scripts/local_quality_evidence.py \
  --revision <ACTUAL_CHECKOUT_HEAD_SHA> > /tmp/local-quality.json

python scripts/phase1_mission_evidence.py \
  --smoke /tmp/local-smoke.json --quality /tmp/local-quality.json \
  --journey /tmp/journey.json --revision <ACTUAL_CHECKOUT_HEAD_SHA> \
  > /tmp/mission.json

python scripts/mission_control_local.py --input /tmp/mission.json --port 8765
```

To see the honest negative case, omit `--quality`: the dashboard keeps quality
**BLOCKED**, even after HTTP CRUD succeeded. A supplied quality document must
be the exact-revision `onecompany.local-quality-evidence.v1` local producer
output, with `status=PASS`, `scope=real_local_http_ui`, and
`deployable=false`; missing/mismatched/foreign scope refuses or blocks.

The producer consumes the canonical real `onecompany.phase1-vertical-smoke.v1`
output with complete owner-supplied draft, read-only planner proposal, actual
localhost health/CRUD and proof that the SQLite fixture was discarded. The
optional journey must be the canonical read-only journey for that SAME project.
Evidence JSON is bounded to 64 KiB per regular file and opened without
following a symlink on supported platforms.

**Trust limits:** A caller-provided revision in the disposable demo is still
UNVERIFIED live GitHub provenance. This bridge does NOT verify GitHub refs,
grant owner authorization, establish a canonical WU/lease/RunKey, produce
independent review or exact-head CI, qualify Playwright, pay a provider,
deploy publicly, or mutate a client project. No once-stopped preview URL is
shown as live; open a separate `python onecompany.py preview-local --port 0`
session if desired once that command has merged. A reported local PASS is
display-only and cannot mint authority. Owner-only spending, credentials,
legal decisions and destructive production operations remain protected.
Phase 2 KServe, OpenViking, Supermemory and ARTEMIS remain planned.
