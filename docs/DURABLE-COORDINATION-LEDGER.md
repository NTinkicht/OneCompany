# Durable Coordination Ledger

`.onecompany/state.json` is deliberately a cache. That means independent scheduled tasks, local CLIs and cloud agents must not rely on one process's private state for leases, material authorship or final gates.

For L4/L5 and orchestrating scheduled supervision, OneCompany therefore uses an optional GitHub Team Room issue as a **durable append-only coordination ledger**.

## What belongs in the ledger

Machine-readable events can include:

```text
ROLE_LEASE_ASSIGNED
ROLE_LEASE_RELEASED
MATERIAL_AUTHOR
GATE
CAPACITY_DEGRADED
CAPACITY_RECOVERED
SUPERVISION_CHECK
HUMAN_DECISION
MERGED
```

The implementation branch does not need a coordination commit every time a lease/gate changes, so exact-head review is not invalidated merely by recording coordination state.

## Trust

Configure:

```json
{
  "enabled": true,
  "issue_number": 123,
  "trusted_publisher_logins": ["owner-login", "github-actions[bot]"]
}
```

Only ledger events posted by configured trusted GitHub publishers are accepted by the reader. Keep the Team Room under repository permissions appropriate to the project; for high-assurance deployments, use dedicated bot/app identities with least privilege rather than a broad human token.

## CLI

```bash
python onecompany.py ledger read --pr 42 --events
python onecompany.py ledger post \
  --type CAPACITY_DEGRADED \
  --actor codex \
  --payload-json '{"capability":"code_review","reason":"quota"}'
```

Provider credentials and sensitive payloads never belong in ledger events.

## Why this matters for scheduled tasks

Four ChatGPT supervisors run in four independent task executions. They need the same durable answer to:

- who holds the implementation lease;
- which actors are already material authors;
- whether the exact current head has a trusted independent gate;
- whether a failover already happened.

Without a shared ledger, four safe-looking supervisors could each start from a different stale local snapshot. The durable ledger plus live PR/CI state makes supervisory checks idempotent across runs.

## Source-of-truth hierarchy

Live GitHub code/PR/CI remains engineering truth. The Team Room ledger is durable coordination truth for facts that cannot safely be committed into the implementation head. `state.json` is derived convenience state.
