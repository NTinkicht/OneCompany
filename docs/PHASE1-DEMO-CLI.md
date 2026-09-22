# Run the first real local OneCompany demonstration

From the **OneCompany source checkout**, use the first-class entrypoint rather than discovering an internal script:

```bash
python onecompany.py brief --target /tmp/oc-demo --repository demo/oc-demo \
  --audience "Families" --problem "Track simple tasks" \
  --outcome "See a local checklist" --first-feature "Add and finish an item" \
  --constraints "No personal data" --save-to /tmp/oc-owner-brief.json

python onecompany.py demo --target /tmp/oc-demo \
  --repository demo/oc-demo --brief /tmp/oc-owner-brief.json \
  --head <CALLER_SUPPLIED_40_HEX_HEAD> --base <DISTINCT_40_HEX_BASE>
```

`python onecompany.py demo --help` displays the required arguments. This command dispatches to the already implemented `scripts/phase1_vertical_smoke.py` integration; it does not create another execution engine. The disposable loopback checklist starts, receives actual health/create/list/complete/delete and refusal requests, and shuts down with its in-memory data discarded. The Create/Adopt target is not written by this demonstration.

A successful `LOCAL_FIXTURE_PROVEN_ONLY` result is intentionally **not** proof of an approved WU, live SHA refs, lease, RunKey, independent review, actual browser test, public deployment, or production readiness. The caller-supplied revisions remain UNVERIFIED and a draft remains unapproved. A stale/invalid saved brief or missing arguments blocks the demo. This source-only demonstration is not installed as a target project's execution command by OneCompany bootstrap; if its helper is missing, the entrypoint explains the limit and returns nonzero. No new provider, API payment, credential or runtime dependency is introduced. Phase2 KServe, OpenViking, Supermemory and ARTEMIS remain planned.
