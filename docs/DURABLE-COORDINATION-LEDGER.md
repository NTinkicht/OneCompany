# Durable Coordination Ledger

`.onecompany/state.json` is a cache. Independent scheduled tasks, local CLIs and cloud agents cannot safely coordinate leases, material authorship or exact-head gates through one process's private state.

For L3 autonomous merge and L4/L5 continuous operation, OneCompany uses an optional GitHub Team Room issue as a durable append-only coordination ledger.

## Events

```text
ROLE_LEASE_ASSIGNED
ROLE_LEASE_RELEASED
ROLE_LEASE_TRANSFERRED
MATERIAL_AUTHOR
GATE
CAPACITY_DEGRADED
CAPACITY_RECOVERED
SUPERVISION_CHECK
HUMAN_DECISION
MERGED
```

Coordination changes do not require a commit to the implementation branch, so recording a gate/lease does not invalidate the exact reviewed SHA.

## Trust

Configure the issue and trusted GitHub publishers in `.onecompany/ledger.json`. Only events posted by those accounts are accepted. The reader orders events using GitHub comment creation time/ID rather than actor-supplied timestamps.

```json
{
  "enabled": true,
  "issue_number": 123,
  "trusted_publisher_logins": ["owner-login", "github-actions[bot]"]
}
```

For high-assurance deployments, prefer dedicated least-privilege bot/app identities. Provider credentials and sensitive payloads never belong in ledger events.

## Concurrency rule

The ledger implements **first valid implementation lease wins**. If two supervisors race to append implementation assignments, the first trusted GitHub event in durable comment order becomes canonical; later overlapping assignments are recorded as conflicts and ignored by derived state. `lease acquire` re-reads the ledger after posting and refuses to proceed unless its own lease is the canonical winner.

A transfer uses one `ROLE_LEASE_TRANSFERRED` event so releasing the old lease and naming its replacement is a single durable coordination transition.

When the durable ledger is enabled, autonomous implementation leases require a PR number. Open a draft/canonical PR before material autonomous writing; this gives authorship and lease history an unambiguous stream identity.

## Dispatch coupling

An unattended write dispatch must name the canonical active lease:

```bash
python onecompany.py dispatch \
  --actor codex \
  --capability implementation \
  --unattended \
  --lease-id <canonical-lease-id>
```

No active durable lease means no unattended writer.

## CLI

```bash
python onecompany.py ledger read --pr 42 --events
python onecompany.py ledger post --type CAPACITY_DEGRADED --actor codex --payload-json '{"capability":"code_review","reason":"quota"}'
```

## Why the four scheduled supervisors need this

Four ChatGPT supervisors are four independent executions. They must converge on the same durable answer to who owns implementation, which actors have material authorship, whether a failover already occurred, and whether the exact live head has a trusted independent gate. The GitHub ledger + live PR/CI makes that coordination idempotent across runs.

Live code/PR/CI is engineering truth. The Team Room ledger is coordination truth for facts that should not be committed into the implementation head. `state.json` is derived convenience state.
