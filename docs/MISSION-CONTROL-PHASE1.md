# Mission Control: your project's actual next step

The Phase-1 loopback-only dashboard reads a **projection**, not the authoritative CompanyOS ledger or GitHub. It is meant to make first-time OneCompany use understandable while never treating a display field as proof of a green check, an owner decision, a lease or deployment.

Run against a locally prepared JSON file:

```bash
python onecompany.py mission-control \
  --input /tmp/onecompany-projection.json \
  --journey /tmp/onecompany-journey.json \
  --port 8765
```

The `--input` file is the JSON produced by `scripts/mission_control_projection.py` (schema `onecompany.mission-control.phase1.v1`); optional `--journey` is the read-only `python onecompany.py journey --json` output (schema `onecompany.first-run-journey.v1`). The dashboard combines only display fields from the journey; it preserves the original exact-revision `checks`, readiness and `authority_granted=false`. Without `--journey`, journey fields will correctly remain missing and no guidance is invented. Both inputs are bounded to 64 KiB, and an unauthorized or non-canonical journey is rejected.

A successful canonical `checks.preview` is a localhost HTTP preview result only; it does **not** count as an actual Playwright/Chromium browser run. Browser evidence stays UNKNOWN until a distinct browser producer supplies it.

The page shows the project, revision, proposed guided stage, quality/HTTP-preview/browser/CI/independent-review **reported** states, blockers, next action, and local preview address if safe. It renders `steps` from the existing read-only guided journey and treats missing fields as UNKNOWN. `READY_FOR_OWNER_PREVIEW` preserves the older UI's READY label, but prominently states that **the projection itself is unverified** and no implementation or deployment authority follows.

An illustrative **canonical-shaped, non-authorizing** input follows. Prefer generating it with the existing `mission_control_projection.py` producer; the values below are examples, not real verification of an application, CI or approval. An older UI-only JSON mock lacking `schema`, `checks`, `authority_granted`, and the draft envelope will now be refused by the CLI.

```json
{
  "schema": "onecompany.mission-control.phase1.v1",
  "project": {"name": "Disposable checklist"},
  "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "product_brief": "DRAFT_UNAPPROVED",
  "execution_core": "BOUNDED",
  "authority_granted": false,
  "checks": {
    "app": {"exact_revision": false, "status": "BLOCKED"},
    "quality": {"exact_revision": false, "status": "BLOCKED"},
    "preview": {"exact_revision": false, "status": "BLOCKED"}
  },
  "readiness": "BLOCKED",
  "stage": "PROPOSAL_READY_NOT_APPROVED",
  "browser": {"status": "UNKNOWN"},
  "ci": {"status": "PENDING"},
  "review": {"status": "UNKNOWN"},
  "blockers": ["A canonical Work Unit has not been approved"],
  "next_action": "Verify live refs and owner authority in trusted planning"
}
```

The server binds only to `127.0.0.1`, checks incoming Host, refuses paths other than `/`, sends `Cache-Control: no-store` and a no-scripts/no-external-resource CSP. All user-supplied values are HTML escaped and bounded. Remote, credentialed, path-bearing or token-bearing preview URLs are suppressed instead of being turned into clickable remote links. Input is bounded to 64 KiB, read through secure no-follow regular-file descriptors, and checked for canonical unapproved schema/fields before serving. It never contacts external services, invokes an AI provider, creates a WU/RunKey/lease, approves a merge or releases a project. The real product #153 vertical acceptance and Phase 2 KServe/OpenViking/Supermemory/ARTEMIS remain separate.
