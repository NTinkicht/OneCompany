# Event-driven handoffs - staged B2

Epic 0.6 B2 prepares repository lifecycle events to wake OneCompany without turning event delivery into authority.

## Current integration state

B2 is deliberately **staged only** on `epic-0.6-integration`.

`.onecompany/handoffs.json` keeps:

- `enabled: false`;
- `mode: staged_only`;
- protected-main B1 proof false;
- protected-main ledger replay proof false;
- activation evidence empty;
- automation publisher trust empty.

This is intentional. Production activation remains blocked until B1 is promoted through protected `main` and a protected-main durable-ledger replay succeeds.

## Reconciliation model

Events are wake hints, never authority. `python onecompany.py handoff` accepts a wake hint and a separately supplied authoritative snapshot. The hint payload is never used to decide authority, exact head/base identity, lease state, CI state, review independence, merge verification, emergency stop, or budget eligibility.

The staged engine supports:

- `WORK_READY` -> bounded dispatch proposal;
- `LEASE_CHANGED` -> bounded execution proposal;
- `PR_CHANGED` / `CI_CHANGED` -> evidence reconciliation;
- `REVIEW_CHANGED` -> promotion reconciliation only for exact-head/base independent review and with any required human Code Owner still satisfied by a human;
- `MERGE_CHANGED` -> successor discovery only from verified, not-yet-processed merge facts;
- `RECONCILE` -> later authoritative reconciliation that can recover a lost or delayed wake event.

Every output has:

- `authority: none`;
- `authority_effects: []`;
- `proposal_only: true`;
- `may_mutate: false`;
- an idempotency key derived from authoritative state rather than delivery ID.

## Safety behavior

The engine fails closed or suppresses consequential proposals when:

- emergency stop is active;
- zero-extra-spend eligibility cannot be verified for dispatch/execution;
- a Work Unit already has a canonical writer;
- a lease is not canonical or does not have exactly one writer;
- CI is not successful;
- review head/base is stale;
- reviewer independence is absent;
- required human Code Owner approval is absent;
- a merge is not verified from live facts or was already processed.

Read-only evidence reconciliation may continue while emergency stop is active.

## Publisher boundary

Automation publisher trust is empty in staged integration. Future automation publishers require a separately reviewed `publisher -> allowed event types` mapping. Both publisher identity and event type must match. A publisher allowed to emit a benign supervision event cannot emit `MERGED`, gate, lease, budget, human-decision, or other authority-bearing events unless explicitly reviewed for that exact event type.

## Activation boundary

Activation is a future, small reviewed change. It must provide evidence that:

1. B1 is present on the current protected default-branch tip;
2. durable Team Room replay succeeded from that protected tip;
3. any automation publisher identity, permissions, zero-spend status, and event-type scope were verified;
4. emergency stop and human-only decisions remain sovereign;
5. no `pull_request_target`, paid event bus, PAYG service, overage, or new paid vendor is introduced.

The integration implementation therefore can be reviewed and merged now without claiming production B2 activation or the required live end-to-end handoff smoke.
