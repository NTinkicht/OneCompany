# Example Work Unit

## WU42 — Prevent unauthorized outbound notifications

**Problem:** An outbox claim can reach a provider without consulting the latest clinic-scoped consent state.

**Objective:** Immediately before provider invocation, unauthorized/missing/revoked delivery is terminally suppressed and the provider is called zero times.

**In scope**
- delivery authorization resolver;
- terminal `suppressed` state;
- privacy-safe reason codes;
- retry/batch exclusion;
- unit and database integration tests.

**Non-goals**
- real SMS/email provider integration;
- contact-value persistence;
- scheduler redesign.

**Acceptance**
- provider called zero times for missing/denied/revoked/mismatched authorization;
- authorized path unchanged;
- suppressed item cannot be re-claimed/retried;
- no contact/message/credential content enters observability;
- required CI green on exact head;
- independent non-author `PASS — MERGE_READY`.

**Budget:** no new paid API/vendor/overage.

**Risk:** HIGH because it controls consent boundary.
