# B2 Event-Driven Handoff Design (Planning Only)

This document is a planning artifact for Epic 0.6 B2 (#50). It does not activate event automation and must not be treated as runtime authority.

## Entry condition

Production B2 code must start only from protected `main` after the B1 promotion is merged and the protected-main ledger replay succeeds. Until then, this document is design only.

## First safe slice

The first B2 implementation should establish a read-only event reconciliation boundary before granting any automation publisher write capability.

A repository event may wake reconciliation, but the event payload is only a hint. Before any consequential action, the handler must re-read and verify:

1. repository identity and protected-default-branch provenance;
2. exact PR/head/base identity when a PR is involved;
3. durable Team Room integrity and current derived state;
4. canonical active lease for write-capable work;
5. actor readiness and exact dispatch mechanism;
6. zero-extra-spend eligibility;
7. emergency-stop state;
8. exact CI/review state and material-authorship independence where promotion evidence is involved.

If any authoritative fact cannot be verified, the handler fails closed and performs no consequential mutation.

## Event identity and deduplication

Each observed delivery should derive a deterministic handoff identity from stable authoritative facts rather than trusting a candidate-provided idempotency token. At minimum, identity should bind:

- repository;
- normalized event class;
- canonical Work Unit where applicable;
- PR number where applicable;
- exact candidate head and trusted base where applicable;
- canonical lease identity for write-capable handoffs;
- target capability/mechanism for dispatch handoffs.

Duplicate, reordered, delayed, and replayed deliveries must converge on one canonical result.

## Publisher policy

B1 trusts only the verified human publisher `NTinkicht`. B2 must not add an automation publisher merely because a workflow can authenticate.

Any future automation publisher requires a separately reviewed capability-scoped policy containing:

- exact observed GitHub login;
- exact execution surface;
- minimum repository permissions;
- zero-extra-spend evidence;
- explicit allowlisted event types;
- explicit forbidden event types;
- proof that the identity cannot satisfy human Code Owner or human-only authority.

The policy shape should be `publisher -> allowed event types`, not a global trusted-publisher boolean.

The initial automated event types, if later approved, should be non-authority observations only. Lease assignment/transfer/renewal/reaping, binding gates, merge facts, human decisions, budget changes, emergency-control changes, and autonomy changes remain excluded until separately reviewed.

## First implementation proof

The first production slice after B1 promotion should prove one read-only lifecycle transition end-to-end:

- a trusted repository lifecycle event wakes the handler;
- live GitHub + Team Room facts are reconciled;
- the handler emits a machine-readable proposal/evidence result only;
- duplicate delivery produces the same result and no duplicate external work;
- stale head/base payloads are rejected by live reconciliation;
- emergency stop prevents any consequential follow-on action;
- no paid route is selected;
- fresh/bootstrap installations keep event automation disabled.

Only after this proof should a mutation-capable publisher or dispatch wake be considered in a later reviewed slice.

## Non-authority rule

Event receipt never creates authority. Events cannot mint leases, grant capabilities, expand credentials, satisfy human review, change budget, clear emergency stop, or promote autonomy. Durable coordination policy plus live GitHub evidence remain authoritative.
