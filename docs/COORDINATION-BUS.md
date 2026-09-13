# Coordination Bus / Team Room

OneCompany recommends one durable GitHub issue as the **Team Room** for cross-agent coordination that does not belong inside a specific PR review thread.

The Team Room is optional infrastructure; GitHub issues/PRs/commits/checks remain the source of truth for the underlying facts.

## Recommended markers

```text
HEARTBEAT
CHECKPOINT
ROLE_LEASE_ASSIGNED
ROLE_RELEASED
CAPACITY_DEGRADED
CAPACITY_RECOVERED
ROLE_FAILOVER
HANDOFF
GATE
PROCESS_PROPOSAL
RETRO_ENTRY
TEAM_DECISION
WAKE
```

Every marker should identify the actor, WU/stream, exact branch/PR/SHA when relevant, and durable evidence.

## Heartbeats

A heartbeat exposes active work; it is not proof of progress. Useful times to post:

- accepting a material lease;
- after a meaningful artifact/result;
- during a genuinely long active session when the runtime naturally permits it;
- before handoff/release/failover;
- when blocked, including the exact blocker.

Do **not** create timer traffic merely to look alive.

## Stale work

A lease that appears stale should not be failed over from clock time alone. Reconcile:

- branch/head movement;
- PR comments/reviews;
- CI/job state;
- provider/runtime evidence;
- current capability state.

Only then release/fail over the affected lease. Never wake multiple implementers onto the same WU as a first response.

## Handoff minimum

```text
HANDOFF
actor_from:
actor_to:
role:
wu:
branch:
pr:
head:
scope:
acceptance:
ci:
findings:
material_authors:
budget/security constraints:
next executable action:
```

A handoff without an executable path is incomplete.

## Wake bus

If you use one Team Room comment stream to trigger unattended agents, restrict triggers to authorized users/actors and parse only explicit markers/mentions. Generic issue text is untrusted input. The wake workflow should provide the bounded task while repository governance remains higher authority.

Generic unattended scouting wakes should be read-only and non-gating by default.

## Slack / Discord / Teams

These are optional attention/culture layers. They may mirror concise notifications but must not become a second lease/review/merge state machine. Important decisions are promoted back to GitHub.

## Secrets

Never put tokens, patient/customer records, private payloads, provider credentials, or secret diagnostic dumps into the Team Room.
