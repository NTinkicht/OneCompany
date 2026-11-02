# Work-plan validator

`python onecompany.py plan workplan-validate --input plan.json --brief brief.json`

Checks a planner-proposed decomposition of an approved owner brief into work units (WUs).
The plan is **untrusted data**: it is parsed and pattern-checked, never executed or obeyed.
The command is offline, reads two bounded regular files (no symlinks, no duplicate JSON
keys, 256 KiB cap), writes nothing, and **admits nothing**: no lease, RunKey, dispatch or
merge decision. Exit code 0 = `ACCEPTED`, 1 = `REFUSED`, 2 = unreadable input.

## Plan shape (`onecompany.workplan.v1`)

`{"schema": "onecompany.workplan.v1", "work_units": [...]}`; each WU has exactly: `id`
(`WU...`), `title` (1-120 chars, no control characters), `requirement_ids`,
`acceptance_criteria` (`{id, text, brief_ref}`), `write_scope` (exact globs), `risk_class`
(`LOW|MEDIUM|HIGH|CRITICAL`), `tests`, `estimate` (`{"lines": n}`), `dependencies`.
`brief_ref` must be `answers.<audience|problem|outcome|first_feature|constraints>` and that
field must be non-empty in the owner's brief.

## Refusals (all collected, sorted, deterministic)

Dependency cycles or unknown/self dependencies; no acceptance criteria or no tests; untraceable
criteria; unscoped/unsafe write scopes; scopes overlapping a protected path (`.github`,
`CODEOWNERS`, `PRODUCT.md`, agent instruction files, `coordination`, `.l5`, owner config and
budget); overlapping scopes not serialized by a dependency; estimates above 400 lines; more
than 12 WUs; unknown fields; any WU mentioning spend, credentials, deployment or production.
The forbidden-work check is a conservative keyword screen and fails closed.

## Output

On acceptance, `proposals` holds `PROPOSED` queue-shaped WUs for one-at-a-time admission
through `approve-brief`, plus the existing `critical_path` and a `next_order` ranked with
`planning_lib.rank_work` while respecting dependencies. `admitted` is always empty and
`authorization` is always `NOT_GRANTED`.
