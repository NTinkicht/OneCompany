# Mission Control: your project's actual next step

The Phase-1 loopback-only dashboard reads a **projection**, not the authoritative CompanyOS ledger or GitHub. It is meant to make first-time OneCompany use understandable while never treating a display field as proof of a green check, an owner decision, a lease or deployment.

Run against a locally prepared JSON file:

```bash
python scripts/mission_control_local.py --input /tmp/onecompany-projection.json --port 8765
```

The page shows the project, revision, proposed guided stage, quality/browser/CI/independent-review **reported** states, blockers, next action, and local preview address if safe. It renders `steps` from the existing read-only guided journey and treats missing fields as UNKNOWN. `READY_FOR_OWNER_PREVIEW` preserves the older UI's READY label, but prominently states that **the projection itself is unverified** and no implementation or deployment authority follows.

An illustrative display-only input:

```json
{
  "project": {"name": "Disposable checklist"},
  "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "readiness": "BLOCKED",
  "stage": "PROPOSAL_READY_NOT_APPROVED",
  "quality": {"status": "UNKNOWN"},
  "browser": {"status": "UNKNOWN"},
  "ci": {"status": "PENDING"},
  "review": {"status": "UNKNOWN"},
  "preview_url": "http://127.0.0.1:8765/",
  "blockers": ["A canonical Work Unit has not been approved"],
  "next_action": "Verify live refs and owner authority in trusted planning"
}
```

The server binds only to `127.0.0.1`, checks incoming Host, refuses paths other than `/`, sends `Cache-Control: no-store` and a no-scripts/no-external-resource CSP. All user-supplied values are HTML escaped and bounded. Remote, credentialed, path-bearing or token-bearing preview URLs are suppressed instead of being turned into clickable remote links. Input is bounded to 64 KiB. It never contacts external services, invokes an AI provider, creates a WU/RunKey/lease, approves a merge or releases a project. The real product #153 vertical acceptance and Phase 2 KServe/OpenViking/Supermemory/ARTEMIS remain separate.
