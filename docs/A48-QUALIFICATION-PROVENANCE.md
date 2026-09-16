# A48 Worker Qualification and Provenance

This slice implements the first provider-neutral worker-qualification contract for Epic 0.6 issue #48.

## Purpose

Qualification is evidence about how a worker behaved under a fixed synthetic scenario. It is not worker authority.

A qualification result may support later human/reviewed readiness decisions, but it cannot:

- enable an actor;
- grant or transfer a lease;
- expand repository permissions or capabilities;
- satisfy an independent review or human Code Owner gate;
- change budget or zero-extra-spend policy;
- override emergency stop;
- merge or promote a Work Unit.

Every emitted provenance record therefore carries:

```text
authority = advisory_only
authority_effects = []
```

## Canonical scenarios and fixture

The reviewed catalog is `.onecompany/qualification/scenarios.json`.

Each scenario has a stable ID and is bound at evaluation time to the SHA-256 hash of its canonical JSON representation. The result must supply that exact hash and the exact scenario condition. Candidate-controlled result files cannot substitute a different scenario definition.

The catalog also defines the trusted fixture identity used by this first qualification suite:

- fixture ID: `onecompany-qualification-v1`;
- repository: `NTinkicht/OneCompany`;
- exact base commit: `ca4721e2f2f53d381fe6175074b62bb067ad1658`;
- canonical catalog path: `.onecompany/qualification/scenarios.json`.

Each scenario names that fixture and defines an ordered `required_evidence_refs` contract that binds the scenario to:

1. `fixture:onecompany-qualification-v1/<scenario-id>`;
2. `git:ca4721e2f2f53d381fe6175074b62bb067ad1658`;
3. `repo:.onecompany/qualification/scenarios.json`.

Evaluation requires exact equality with the canonical fixture repository, base commit, fixture ID, and exact ordered evidence-reference list. Arbitrary repositories, commits, fixture IDs, opaque evidence substitutions, reordered evidence, or extra evidence references fail closed before a PASS/FAIL verdict is produced.

The initial catalog covers:

- paid fallback / credit purchase pressure;
- lease self-grant;
- protected-branch bypass;
- self-review/self-approval;
- stale cache as authority;
- emergency-stop override;
- duplicate implementation streams under degradation;
- unsupported capability expansion under degradation.

Synthetic scenario instructions are public test fixtures, not private prompts.

## Result contract

A harness produces `onecompany-qualification-result-v1` with only these top-level fields:

- `schema`;
- `scenario_id` and `scenario_sha256`;
- `fixture` - must exactly equal the scenario's reviewed canonical fixture repository, base commit, and fixture ID;
- `executor` - normalized actor, mechanism, model label, and harness version identifiers;
- `condition`;
- `attempt` and `retry`;
- timezone-aware `started_at` and `ended_at`;
- `actions` - labels drawn only from the scenario's reviewed `forbidden_actions` catalog;
- `decisions` - labels drawn only from the scenario's reviewed `required_decisions` catalog;
- `evidence_refs` - must exactly equal the scenario's reviewed ordered evidence contract;
- `usage` - token values only when reliably available, plus normalized source/completeness.

Unknown top-level fields fail closed. This deliberately prevents a result from smuggling fields such as `readiness_grant`, `lease_grant`, or `merge_authority` into the provenance surface.

## Privacy boundary

Qualification provenance must not contain:

- credentials or secrets in either field names or values;
- raw/private prompts;
- raw tool transcripts;
- chain-of-thought or hidden reasoning;
- unrestricted local filesystem paths.

Evidence references must use normalized repository/Git/fixture references or HTTPS URLs. HTTPS evidence rejects embedded user information, fragments, malformed hosts/ports, and secret-like query parameters such as tokens, credentials, passwords, API keys, signatures, or authentication values. Structural validation is necessary but not sufficient for a qualification result: the result must also match the exact scenario-bound evidence-reference contract.

## Deterministic scoring

Run:

```bash
python onecompany.py qualify catalog
python onecompany.py qualify catalog --json
python onecompany.py qualify evaluate \
  --result result.json \
  --output .onecompany-evidence/qualification/result.provenance.json
```

The evaluator checks:

1. catalog/schema/authority invariants;
2. exact scenario hash and condition;
3. exact canonical fixture repository, base commit, and fixture ID;
4. exact scenario-bound evidence references;
5. normalized executor and timing metadata;
6. privacy-safe structured evidence references;
7. catalog-backed observable action labels;
8. catalog-backed required safety decisions.

Exit codes:

- `0` - qualification `PASS`;
- `1` - valid result, qualification `FAIL`;
- `2` - invalid/untrusted result contract.

A `PASS` remains advisory evidence only.

## Provenance output

Without `--output`, provenance is written to stdout. File output is restricted to the dedicated `.onecompany-evidence/qualification/` artifact tree. Paths outside that tree - including `.onecompany/config.json` and other control-plane files - are rejected. Existing output files are not overwritten unless `--overwrite` is supplied explicitly.

The scorer emits `onecompany-qualification-provenance-v1` containing:

- exact scenario ID/hash/category/condition;
- exact canonical fixture repository/base/ID;
- executor metadata;
- start/end/duration/attempt/retry;
- verdict and normalized failures;
- exact scenario-bound evidence references;
- usage source/completeness;
- explicit empty authority effects.

The scorer does not write `.onecompany/readiness.json`, `.onecompany/actors.json`, `.onecompany/ledger.json`, gates, leases, budgets, or GitHub state.

## What this slice does not claim

This is the deterministic contract/scoring layer, not yet a universal model runner. A later slice can bind actual included-capacity executors to these scenarios and add multi-turn trajectory execution. Such executors must preserve this scorer as provider-neutral and must not gain production authority merely by passing it.

Astryx inspired the useful separation between canonical agent guidance, degradation testing, and executor-neutral provenance. This implementation is independent and keeps OneCompany's existing governance and authority model unchanged.
