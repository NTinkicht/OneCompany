---
name: OneCompany Team Room
title: "OneCompany Team Room"
about: Permanent durable coordination bus for agents and human operators
labels: "coordination"
---

# Team Room

Keep this issue open permanently. Record only durable coordination signals; GitHub code/PR/CI remains engineering truth.

Supported markers include:

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
SUPERVISION_CHECK
PROCESS_PROPOSAL
RETRO_ENTRY
TEAM_DECISION
WAKE
```

Do not post secrets, credentials, private provider payloads, sensitive production data, or raw prompts containing protected information.

A heartbeat is visibility, not proof of progress. Scheduled supervisors must reconcile durable branch/PR/CI evidence before declaring a lease stale or failing it over.
