# Phase 1: first real local vertical smoke (#153)

This command connects the **existing** discovery, owner-filled Product Brief, read-only proposed planning handoff, and real disposable checklist fixture. It is a local demonstrator, not a newly created canonical Work Unit or an authorized agent run.

Use an empty disposable Create directory, or an existing Adopt directory that contains no private data. From a trusted OneCompany checkout:

```bash
python onecompany.py brief --target /tmp/oc-demo --repository demo/oc-demo \
  --audience "Families" --problem "Track simple tasks" \
  --outcome "See a local checklist" --first-feature "Add and finish an item" \
  --constraints "No personal data" --save-to /tmp/oc-owner-brief.json
python scripts/phase1_vertical_smoke.py --target /tmp/oc-demo \
  --repository demo/oc-demo --brief /tmp/oc-owner-brief.json \
  --head <CALLER_SUPPLIED_40_HEX_HEAD> --base <DISTINCT_40_HEX_BASE>
```

The smoke checks the saved brief against **fresh** discovery, creates a non-authorizing handoff using the actual planner consumer, starts the existing SQLite-in-memory localhost app on an ephemeral port, probes its real health endpoint, and sends actual create/list/complete/delete HTTP calls. It also checks duplicate deletion returns 404 and a cross-origin POST is refused. The server is shut down, its store closed, and no target source files are created or changed.

The result `LOCAL_FIXTURE_PROVEN_ONLY` means exactly that. Both supplied 40-hex revisions are marked **unverified**. It does *not* verify live GitHub refs, real Playwright/Chromium in that invocation, CI, independent review, a canonical work-unit lease, owner implementation approval, credentials, remote deployment or production readiness. The approved trust path must separately verify each of those before a release. CI for this feature runs the integration's actual local HTTP tests. Browser qualification remains the separate #175/#177 workflow evidence.

A changed Create/Adopt assessment or forged authorization in the saved Product Brief refuses before any local app starts. Errors abort and dispose of the ephemeral app. This is bounded, provider-neutral and zero extra AI spend. KServe, OpenViking, Supermemory and ARTEMIS remain planned for Phase 2.
