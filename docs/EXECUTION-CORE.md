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

All state-changing operations compare the caller's `RunKey` to the current one. Revising the objective or deliberately failing over rotates the generation. A late worker response from an older generation is rejected with `StaleGenerationError`.

This prevents an obsolete worker from mutating a newer execution after reconciliation or failover.

## Persistent objective and tactical work

`RunContext` contains the durable bounded objective, acceptance criteria, current state, tasks, evidence, lessons, resource usage, progress fingerprint, and completion state.

`ObjectiveTracker` owns objective changes and rotates the generation on revision.

`TaskBoard` tracks tactical work. Task state is not completion evidence by itself.

`EvidenceRegistry` stores authoritative and non-authoritative evidence plus bounded `decision`, `evidence`, and `dead_end` lessons. Lessons are capped so execution context cannot grow without bound.

## Evidence-driven completion

A worker completion claim moves an active run to `completion_pending`. `CompletionGate` then requires:

- every acceptance criterion to have at least one authoritative evidence reference;
- every tracked task to be complete;
- no blocked tasks;
- no blocked execution state.

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

`ExecutionSupervisor` responds with safe recommendations such as `RECONCILE_OR_FAILOVER`; it does not transfer the implementation lease itself.

## Resource guard

Per-run bounds may include:

- assistant-token ceiling;
- active-time ceiling;
- consecutive-error ceiling;
- unchanged-progress ceiling.

Budget exhaustion pauses/degrades execution. It never enables a paid fallback or changes global OneCompany budget policy.

## Deterministic transition engine

`TransitionEngine.transition(...)` is copy-based and has no filesystem, network, subprocess, or wall-clock lookup. Time is injected by the caller. This keeps lifecycle behavior deterministic and directly unit-testable.

Supported state-control commands are:

- `pause`;
- `resume`;
- `block`;
- `unblock`;
- `budget_limit`;
- `rotate_generation`.

## Execution journal

`ExecutionJournal` writes append-only JSONL records. Each record contains:

- a monotonic sequence;
- event type;
- current RunKey;
- event details;
- previous record hash;
- complete state hash;
- event timestamp;
- record hash.

Verification fails closed if sequence or hash-chain integrity is broken.

`ExecutionStore` atomically writes the current RunContext and appends journal evidence. Runtime files live under `.onecompany/runtime/execution/`, which is intentionally ignored by Git.

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

Examples:

```bash
python onecompany.py execution create \
  --wu WU-42 \
  --objective "Implement bounded retry policy" \
  --acceptance-criterion AC1="unit tests pass" \
  --acceptance-criterion AC2="retry remains bounded"

python onecompany.py execution task-add --wu WU-42 --task-id T1 --description "Implement policy"
python onecompany.py execution evidence-add --wu WU-42 --evidence-id E1 --kind test --reference test_retry_policy --acceptance-criteria AC1,AC2 --authoritative
python onecompany.py execution progress --wu WU-42 --head HEAD_SHA --unmet-ac AC2 --test unit=passing --evidence-id E1
python onecompany.py execution claim --wu WU-42 --claim "Implementation objective is complete"
python onecompany.py execution evaluate --wu WU-42 --verdict met --confidence 1.0 --notes "Evidence verified" --cited-evidence E1
python onecompany.py execution journal-verify --wu WU-42
```

## Independent implementation note

The Execution Core is specified and implemented as native OneCompany Python code. No third-party source, tests, prompts, comments, schemas, or documentation text are incorporated into these files.
