# OneCompany Execution Core

The Execution Core manages bounded worker execution **inside an already-authorized Work Unit lease**. It is deliberately subordinate to OneCompany governance: it cannot create or transfer leases, grant reviewer independence, relax budget policy, or merge code.

## Boundary

```text
OneCompany governance / WU lease
            |
            v
      Execution Core
            |
   +--------+---------+
   |                  |
RunContext       ExecutionJournal
   |                  |
   +--> ObjectiveTracker
   +--> TaskBoard
   +--> EvidenceRegistry
   +--> ProgressSentinel
   +--> ResourceGuard
   +--> CompletionGate
   +--> TransitionEngine
   +--> AgentRuntimeAdapter
   +--> ExecutionSupervisor
            |
            v
     CI / assurance
            |
            v
independent exact-head/base review
            |
            v
      merge authority
```

A successful Execution Core completion verdict means only that the bounded implementation objective has enough execution evidence to proceed to normal OneCompany CI and independent review. It is never a merge gate.

## Execution identity and stale-generation fencing

Every execution is addressed by:

```text
wu_id + run_id + generation
```

Every existing-state mutation must carry all three values. Core APIs compare the supplied `RunKey` to the current one, and the public CLI requires `--run-id` plus `--generation` for all state-changing commands after `create`.

Revising the objective or deliberately failing over rotates the generation. A late worker response from an older generation is rejected with `StaleGenerationError`; the CLI does not silently substitute the latest generation.

This prevents an obsolete worker from mutating a newer execution after reconciliation or failover.

## Persistent objective and tactical work

`RunContext` contains the durable bounded objective, acceptance criteria, current state, tasks, evidence, lessons, resource usage, progress fingerprint, and completion state.

`ObjectiveTracker` owns objective changes and rotates the generation on revision.

`TaskBoard` tracks tactical work. Task state is not completion evidence by itself. A `complete` run is terminal: tasks cannot be changed and terminal state cannot be reopened through `block` or `budget_limit`.

`EvidenceRegistry` stores authoritative and non-authoritative evidence plus bounded `decision`, `evidence`, and `dead_end` lessons. Evidence mutations are rejected while the run is non-runnable or a resource/stall guard is tripped.

## Evidence-driven completion

A worker completion claim moves an active, guard-clear run to `completion_pending`. `CompletionGate` then requires:

- every acceptance criterion to have at least one authoritative evidence reference;
- every tracked task to be complete;
- no blocked tasks;
- a runnable lifecycle state;
- a clear resource/stall guard.

A worker's own statement is not authoritative evidence.

An evaluator may return:

- `continue`;
- `met`;
- `impossible`;
- `unavailable`.

The evaluator cannot force `met` when deterministic evidence requirements are missing. `met` moves only the execution session to complete; normal OneCompany CI, assurance, reviewer independence, exact-head/base gate, and merge policy remain mandatory.

## Progress versus activity

`ProgressSentinel` fingerprints substantive execution facts:

- current HEAD SHA;
- unmet acceptance criteria;
- test state;
- blockers;
- evidence IDs;
- material changes.

Repeated heartbeats, comments, rereads, Todo reordering, or identical failing retries do not alter this fingerprint. Repeated unchanged fingerprints trip the configured stall limit.

When a configured resource/stall limit trips, the state-changing CLI persists a non-runnable state before returning. Token/time exhaustion becomes `budget_limited`; repeated-error or unchanged-progress exhaustion becomes `paused`. `ExecutionSupervisor` then emits the appropriate recommendation, such as `RECONCILE_OR_FAILOVER`, but it still cannot transfer the canonical WU lease.

## Resource guard

Per-run bounds may include:

- assistant-token ceiling;
- active-time ceiling;
- consecutive-error ceiling;
- unchanged-progress ceiling.

A tripped guard is durable state, not just an advisory message. Evidence and completion mutations remain rejected until the run is runnable and the guard is clear. For repeated-error or unchanged-progress exhaustion, an authorized lifecycle action may recover a paused run once the guard condition has been reconciled. Assistant-token or active-time exhaustion is cumulative for the existing `RunContext`: `resume` and `rotate_generation` do not reset those counters or clear `budget_limited`. Recovery therefore requires creating a successor `RunContext` under normal OneCompany authorization rather than implicitly resetting or raising the exhausted budget. Budget exhaustion never enables a paid fallback or changes global OneCompany budget policy.

## Deterministic transition engine

`TransitionEngine.transition(...)` is copy-based and has no filesystem, network, subprocess, or wall-clock lookup. Time is injected by the caller. This keeps lifecycle behavior deterministic and directly unit-testable.

Supported state-control commands are:

- `pause`;
- `resume`;
- `block`;
- `unblock`;
- `budget_limit`;
- `rotate_generation`.

`complete` is terminal. `block`, `budget_limit`, task mutations, and generation rotation cannot reopen or mutate a completed run.

## Serialized state mutation and execution journal

Each work unit has one OS-level exclusive lock shared by:

- the CLI create existence check;
- every existing-state read-modify-write cycle;
- recovery;
- journal sequence/hash assignment.

The lock is held from the initial state read through mutation and `persist_event`, preventing concurrent commands from overwriting each other.

`ExecutionJournal` writes append-only JSONL records. Each new record contains:

- a monotonic sequence;
- event type;
- current RunKey;
- event details;
- previous record hash;
- complete state hash;
- event timestamp;
- transaction operation ID;
- record hash.

Verification fails closed if sequence or hash-chain integrity is broken.

`ExecutionStore` keeps atomic current-state persistence separate from the journal while using a durable write-ahead pending marker to bridge the two files:

```text
per-WU lock
   |
write pending operation
   |
atomic state replace
   |
journal append + fsync
   |
remove pending marker
```

If a process stops after the pending marker or state write, the next locked `load`, mutation, or journal verification finishes the pending operation. If the journal record was already committed, recovery recognizes its operation ID and only reconciles state/marker cleanup. After recovery, `load` verifies that the state hash exactly matches the latest journal record; unjournaled state is rejected.

Runtime files live under `.onecompany/runtime/execution/`, which is intentionally ignored by Git.

## Worker profiles

`.onecompany/execution-profiles.json` adds advisory execution metadata without replacing the existing eligibility router. Profiles declare:

- roles;
- role-specific light/standard/heavy tiers;
- preferred complexity;
- existing OneCompany cost class;
- context strength.

`rank_worker_profiles` ranks only candidates allowed by the caller's existing cost-policy set. Permission, readiness, lease, capacity, authorship, and dispatch eligibility remain upstream OneCompany responsibilities.

## External runtime adapter

`AgentRuntimeAdapter` is a generic interface. `CommandRuntimeAdapter` provides a dependency-free implementation using:

- explicit argv arrays;
- `shell=False`;
- JSON on stdin;
- bounded timeout;
- environment allowlisting.

The request includes the current RunKey, objective, role, and bounded payload. The adapter carries no OneCompany lease, review, budget, or merge authority.

## CLI

The entry point is:

```bash
python onecompany.py execution ...
```

`create` establishes the first `run_id` and `generation`. Its JSON output contains the current key. Copy those exact values into subsequent state-changing commands.

Example:

```bash
python onecompany.py execution create \
  --wu WU-42 \
  --run-id RUN-42 \
  --objective "Implement bounded retry policy" \
  --acceptance-criterion AC1="unit tests pass" \
  --acceptance-criterion AC2="retry remains bounded"

python onecompany.py execution task-add \
  --wu WU-42 --run-id RUN-42 --generation 1 \
  --task-id T1 --description "Implement policy"

python onecompany.py execution evidence-add \
  --wu WU-42 --run-id RUN-42 --generation 1 \
  --evidence-id E1 --kind test --reference test_retry_policy \
  --acceptance-criteria AC1,AC2 --authoritative

python onecompany.py execution progress \
  --wu WU-42 --run-id RUN-42 --generation 1 \
  --head HEAD_SHA --unmet-ac AC2 --test unit=passing --evidence-id E1

python onecompany.py execution claim \
  --wu WU-42 --run-id RUN-42 --generation 1 \
  --claim "Implementation objective is complete"

python onecompany.py execution evaluate \
  --wu WU-42 --run-id RUN-42 --generation 1 \
  --verdict met --confidence 1.0 --notes "Evidence verified" \
  --cited-evidence E1

python onecompany.py execution journal-verify --wu WU-42
```

If an `edit` or `rotate_generation` command succeeds, use the **new generation returned in the command output** for every later mutation. A worker holding the previous generation will be rejected.

## Independent implementation note

The Execution Core is specified and implemented as native OneCompany Python code. No third-party source, tests, prompts, comments, schemas, or documentation text are incorporated into these files.
