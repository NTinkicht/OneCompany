# Configuration Reference

The reference control plane lives in `.onecompany/`. JSON is used intentionally so validation and automation do not require a YAML dependency.

## `config.json`

### `schema_version`
Control-plane format version.

### `project`
- `name` — human project name.
- `repository` — `owner/name` for GitHub-aware tooling.
- `source_of_truth` — reference model requires `github`.
- `default_branch` — normally `main`.

### `autonomy`
- `level` — L0-L5.
- `continue_when_ready_work_exists` — enables continuous queue behavior; expected true at L4/L5.
- `human_must_approve_autonomy_increase` — safe default true.

### `delivery`
- `single_canonical_stream` — exactly one implementation stream for a bounded WU/company policy scope.
- `require_explicit_implementation_lease` — no inferred ownership.
- `require_exact_head_gate` — final approval bound to SHA.
- `require_independent_non_author_review` — separation of powers.
- `required_finding_resolution_severity` — default `MEDIUM`.
- `require_expected_head_merge` — merge executor verifies approved SHA.
- `derive_state_from_github_before_consequential_actions` — stale cache cannot govern merge/failover.

### `coordination`
Defines which channels are authoritative. Reference settings keep chat/Slack advisory.

### `no_idle`
- `enabled` — turn on for continuous autonomy.
- `fault_when_ready_work_has_no_valid_lease` — core no-idle invariant.
- `measure_progress_by_durable_artifacts` — do not trust acknowledgements as heartbeat.
- `allow_idle_specialists` — prevents utilization theater.

### `human_only_decisions`
Version-controlled list of action classes requiring a human.

## `budget.json`

### `ai.additional_monthly_spend_cap`
Maximum new AI spend allowed beyond already-owned subscriptions/allowances/local compute.

### Paid-switch booleans
`allow_paid_fallback`, `allow_overage`, `allow_auto_topup`, `allow_new_paid_vendor` are separate because products can expose these independently.

### `unknown_cost_behavior`
- `forbid` — safest;
- `human_approval` — stop and ask authorized human;
- `allow_within_cap` — only appropriate with reliable metering/cap enforcement.

### Cost classes
Actors are routed only if their cost class is allowed/conditionally allowed by current budget.

## `actors.json`

Each actor has:

- stable `id`;
- display name;
- `enabled` and `configured` separately;
- execution modes;
- cost class;
- permission summary;
- capabilities;
- self-gate policy.

Why both enabled/configured? A known actor template can exist without being connected. `enabled=true` with `configured=false` is a validation error.

## `roles.json`

Roles define purpose, required capabilities, write scope, and conflicts. They are not bound permanently to actor IDs.

## `patterns.json`

Catalogs the organizational/technical patterns the company relies on. Each entry records an ID, adoption level, origin, source, and purpose. The corresponding human-readable contract lives under `patterns/<id>.md`.

Adoption levels:

- `core` — part of the reference safety/coordination model;
- `recommended` — broadly useful but may be replaced by an equivalent mechanism;
- `optional` — project-dependent;
- `experimental` — evaluate before granting authority.

Pattern provenance is documentation, not execution permission.

## `overlays.json`

Registers optional professional role overlays plus their provenance and hard non-authority rules.

An overlay can focus an actor on backend architecture, database reliability, security, SRE, code review, persona testing, minimal-change remediation, or multi-agent-system design. It does **not** create a new actor or independent reviewer.

The reference validator requires these overlay rules to remain false:

- creates actor/capacity;
- creates implementation lease;
- grants repository permission;
- overrides material authorship;
- overrides self-gate rule;
- grants merge authority.

Overlay files live under `overlays/`.

## `queue.json`

A compact dependency index for proposed/planned WUs. Once work begins, the GitHub issue/PR is the durable detailed record. Keep IDs/dependencies/statuses consistent.

## `state.json`

Operational cache. Important fields:

- repository/default head;
- current WU/PR/head;
- active leases;
- current exact-head gate summary;
- ready-work count;
- blockers/human-decision flag.

Always reconcile before consequential action.

## Adding project-specific fields

Schemas intentionally allow some extension. Prefix project-specific concepts clearly and update validation if they affect safety or routing. Do not hide new spending/permission semantics in an opaque extension field.
