# Lessons That Shaped OneCompany

OneCompany captures generic multi-agent operating lessons as system constraints rather than bundling any specific project's history into its product.

## 1. “Assigned” is not “working”

An agent can acknowledge a task without producing an artifact. Progress should be measured from durable repository events, not conversational intent.

**Design consequence:** lease heartbeat/no-idle logic tracks commits, PR updates, CI/review execution, and state transitions.

## 2. More agents can mean less progress

Multiple workers independently solving the same small blocker create conflicting branches, duplicated spend/capacity, and unclear authority.

**Design consequence:** one canonical implementation lease per bounded WU.

## 3. Failover should switch worker, not reality

When a preferred worker hits quota, opening a fresh branch discards context and creates races.

**Design consequence:** failover continues on the same branch/PR/head and preserves cumulative authorship.

## 4. Roles cannot be permanently attached to brands

A worker may be excellent at coding today, quota-limited tomorrow, or gain a new GitHub capability later.

**Design consequence:** capability routing with preferences, not permanent identity→job bindings.

## 5. Reviews silently become stale

A reviewer may approve commit A, then a “tiny fix” creates commit B.

**Design consequence:** every final gate is exact-SHA; a moved head requires refreshed confirmation.

## 6. Deterministic tool failures need deterministic tools

Repeatedly hand-editing formatting based on visual guesses can fail several times while the canonical formatter could resolve it immediately.

**Design consequence:** reproduce with repository-pinned executable tooling before speculative remediation; fail over to a worker/environment that can execute the tool.

## 7. Model quota is an operational dependency

Code-review quota can be exhausted even when general model access remains available.

**Design consequence:** capability-specific capacity state and explicit fallback chains.

## 8. Budget promises must be machine-readable

“Don’t spend extra” is too easy to violate accidentally when products offer credits/overage/fallback APIs.

**Design consequence:** hard financial governor; unknown/metred paths are ineligible when forbidden.

## 9. Company state becomes stale

A checked-in `STATE.json` may say no PR is active while live GitHub has moved several Work Units ahead.

**Design consequence:** state is a derived cache; reconciliation against GitHub precedes consequential action.

## 10. Communication channels multiply truth

GitHub, chat, Slack, model memory, and documents can disagree.

**Design consequence:** GitHub is durable source of truth; other channels are attention/reasoning layers.

## 11. Independent review requires authorship awareness

When orchestration fails over between actors, the latest committer may not be the material author.

**Design consequence:** preserve cumulative material authorship and enforce non-author gating on the candidate head.

## 12. Read-only specialists are valuable

Not every agent needs write authority. Repository intelligence, regression scouting, test design, and failure analysis can be safely useful with reduced permissions.

**Design consequence:** capability and permission are separate dimensions.

## 13. “Autonomous” needs a stop rule

An unattended loop without a clear human override is not mature autonomy.

**Design consequence:** explicit human-only decisions, autonomy levels, and incident stop procedures.

## 14. No-idle should not mean busywork

Forcing every actor to emit activity wastes capacity and can degrade quality.

**Design consequence:** the company optimizes Work Unit throughput and risk closure, not per-agent utilization. Idle specialists are fine; idle ready work is the fault.

## 15. Positive test fixtures must resemble real provider payloads

An in-memory GitHub double returning one-line Base64 or a successful check name
without app/run identity may let synthetic tests pass while a real installation
fails or a forged success is accepted.

**Design consequence:** test provider-native wrapped content, malformed JSON,
ambiguous mutation results, exact diff and ancestry, GitHub Actions job/run
provenance, trusted workflow identity and independently sourced check results.
Do not mistake a passing source simulation for a completed live pilot.

## 16. Preconditions must precede the first external write

A worker that checks run IDs, cost class or actor availability after creating
its PR can leave a durable mutation without reproducible provenance.

**Design consequence:** validate complete zero-extra-spend policy, actor cost and
capacity, temporary outages, repository/base and immutable run identity before
calling mutation APIs. A malformed response after a successful API mutation is
uncertain; reconcile the canonical remote identity instead of blindly retrying.

## 17. Review policy and enforcement code must describe the same system

Updating CODEOWNERS or a runbook alone does not update `inspect_enforcement`,
`doctor` and `github-audit`. A stale mandatory review predicate can make
otherwise compliant technical delivery appear blocked.

**Design consequence:** modify policy, machine validators, operational reports
and negative regression coverage in the same PR. Keep technical status-check
verification explicit and independent of optional reviewer assignment.
