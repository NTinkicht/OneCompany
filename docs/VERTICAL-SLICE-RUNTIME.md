# First real, disposable application runtime

Phase 1 [#151](https://github.com/NTinkicht/OneCompany/issues/151) is a
**working local application**, not another policy simulation, SaaS deployment or
claim that the full build–test–merge–preview pipeline is qualified.

```bash
python examples/vertical-slice/app.py --port 8765
# Visit http://127.0.0.1:8765/ in a browser.
python -m unittest discover -s .onecompany/selftest -p 'test_vertical_slice.py'
```

This sign-inless checklist supports adding, listing, completing, undoing and
deleting items through actual HTTP JSON endpoints. SQLite is deliberately
**in-memory** for disposable use; items disappear when stopped. The page uses
DOM-safe `textContent`, basic accessible form/status controls and a restrictive
Content Security Policy. A local-only bind, Host/Origin checks, a non-simple
mutation header and bounded JSON/title validation limit local fixture attack
surface. No credentials or remote data are required. Do not deploy publicly,
store sensitive information, or mistake the local mutation header for
production authentication/authorization.

`GET /health` supplies bounded local readiness; `GET /api/items` lists items,
`POST /api/items` creates, `PATCH /api/items/{id}` changes `done`,
`DELETE /api/items/{id}` removes. Browser JavaScript adds the
`X-OneCompany-Local: 1` header for mutations; this is only a local
cross-origin-request guard. Tests connect to a **real ephemeral localhost
HTTP port**, perform a complete CRUD round trip, inspect static UI/CSP and
reject bad Host/Origin, malformed IDs, oversized/malformed JSON and non-bool
`done`.

Next (separate WU): bind actual app build/runtime identity to the canonical WU,
RunKey, workspace and exact PR SHA, capture deterministic HTTP/browser evidence,
and present it via Mission Control. The framework must enforce leases and
independent review before eligible merge. A green unittest result or a browser
opening on the developer's computer is not a production/preview qualification.
