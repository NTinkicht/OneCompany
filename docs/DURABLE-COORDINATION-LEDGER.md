# Durable Coordination Ledger

`.onecompany/state.json` is a cache. Independent scheduled tasks, local CLIs and cloud agents cannot safely coordinate concurrent WU leases, material authorship or binding exact-head/base gates through one process's private state.

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

Coordination changes do not require a commit to an implementation branch, so publishing a lease/gate does not itself change the candidate head.

## Trust

Configure the issue and trusted GitHub publishers in `.onecompany/ledger.json`. Only events posted by trusted publishers are accepted. The reader orders events using GitHub comment creation time/ID rather than actor-supplied timestamps.

```json
{
  "enabled": true,
  "issue_number": 123,
  "trusted_publisher_logins": ["owner-login", "github-actions[bot]"]
}
```

For high-assurance deployments, prefer dedicated least-privilege bot/app identities. Credentials and sensitive payloads never belong in ledger events.

## Concurrency model

The durable invariant is **first valid canonical lease wins per Work Unit**, subject to company-wide flow policy.

A new implementation lease is accepted only when all applicable constraints hold:

- no active implementation lease already owns the same WU;
- total active implementation streams remain inside the configured WIP limit;
- candidate dependencies are satisfied;
- declared write scopes do not conflict with active WUs;
- semantic resource locks do not conflict;
- risk policy permits parallel execution;
- the selected actor still has verified implementation capacity.

If concurrent supervisors append competing assignments, the first trusted event in durable GitHub order that satisfies the policy becomes canonical. Later invalid/overlapping claims are retained as conflicts and ignored by derived canonical state. `lease acquire` re-reads the ledger after publication and proceeds only if its own lease survived derivation as canonical.

This means two **independent** WUs can legitimately hold leases at the same time while duplicate/conflicting writers cannot.

## Failover

A transfer uses one `ROLE_LEASE_TRANSFERRED` event so releasing the old writer and naming its replacement is one durable transition.

Failover is WU-scoped:

```text
WU-A / PR 40 / codex  -> transfer -> claude
WU-B / PR 41 / gemini -> remains untouched
```

The replacement inherits the same canonical WU/branch/PR and cumulative material-authorship history. Failover changes the worker, not the stream.

## PR identity

When the durable ledger is enabled, autonomous implementation leases require an associated PR number. Open a draft/canonical PR before material unattended implementation so lease, authorship, CI, gate and merge history share an unambiguous stream identity.

The approved planning baseline should also map the WU to its issue/branch/PR once known. Reconciliation may repair caches, but it must not invent a second canonical stream.

## Binding gates

A durable `GATE` records, at minimum:

```text
PR
candidate head SHA
candidate base SHA
reviewer actor
material-author snapshot
verdict
durable evidence references
scope-verification result
```

A gate becomes stale when material authorship changes, the candidate head moves, or the reviewed base moves. A parallel merge of another WU therefore invalidates stale integration evidence even when this WU's head itself is unchanged.

The merge executor re-checks live changed-file scope, reviewer eligibility, head/base identity, required checks, governance sensitivity and evidence before mutation.

## Dispatch coupling

An unattended write dispatch must name the canonical active lease:

```bash
python onecompany.py dispatch \
  --actor codex \
  --capability implementation \
  --unattended \
  --lease-id <canonical-lease-id>
```

No active durable lease means no unattended writer. A routing choice alone is never implementation authority.

## CLI

```bash
python onecompany.py ledger read --pr 42 --events
python onecompany.py ledger post \
  --type CAPACITY_DEGRADED \
  --actor codex \
  --payload-json '{"capability":"implementation","reason":"quota"}'
```

## Why replicated supervisors need this

Several supervisors are independent executions. They must converge on the same durable answers to:

- which WUs currently have canonical writers;
- whether a new WU is conflict-safe to admit;
- which actor owns each stream;
- whether a failover already occurred;
- cumulative material authorship per PR;
- whether a current head/base pair has a trusted independent gate;
- whether another merge made that base stale.

The GitHub ledger plus live PR/CI/review state makes those decisions reconstructible and idempotent across runs.

## Source-of-truth split

```text
versioned .onecompany graph = approved planning / policy baseline
live GitHub PR/CI/review    = execution evidence
Team Room ledger            = durable coordination facts that should not mutate candidate heads
state.json                  = derived convenience cache only
```

No chat history, local process memory or stale state file may override those sources.
