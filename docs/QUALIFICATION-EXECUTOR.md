# Verified qualification executor baseline

Epic 0.6 issue #48 binds the qualification harness to the already verified `onecompany-local` executor without expanding production authority.

## Purpose

The baseline proves that the provider-neutral qualification pipeline is executable end to end through an enabled, configured, unattended, zero-extra-spend actor. It is a deterministic control baseline, not an LLM benchmark score and not evidence that disabled providers are ready.

Run the complete catalog:

```bash
python onecompany.py qualify-worker --json
```

Run one canonical scenario:

```bash
python onecompany.py qualify-worker --scenario Q-STOP-001 --json
```

## Binding requirements

Every run revalidates the current repository control plane. The binding is accepted only when all of these remain true:

- actor: `onecompany-local`;
- mechanism: `onecompany-actions-readonly`;
- verified capability: `repository_intelligence`;
- actor and mechanism are enabled/configured for unattended use;
- repository access is read-only, with no write/review/merge access;
- cost class is `FREE_ALLOWANCE`;
- budget keeps additional spend at zero and forbids paid fallback, overage, auto top-up, new paid vendors and unknown cost.

Any capability expansion, readiness loss, permission expansion, mechanism drift, or budget relaxation blocks execution before a scenario is scored.

## Scenario execution

The baseline executes the canonical eight-scenario catalog. One-shot scenarios execute once. `degradation_turn_6` and `degradation_turn_10` execute six and ten turns respectively, so late drift is observable rather than inferred from a one-shot result.

The deterministic policy map is intentionally explicit and must exactly match the canonical scenario contract. If the catalog changes without a corresponding reviewed baseline update, execution fails closed with `scenario_contract_drift`.

## Authority boundary

Qualification is always advisory:

- `authority = advisory_only`;
- `authority_effects = []`;
- `production_write_authority = false`;
- it cannot create readiness, leases, gates, budget exceptions, dispatch authority, merge authority or emergency-stop authority;
- it does not mutate `.onecompany/actors.json`, `readiness.json`, `dispatch.json`, `budget.json` or `ledger.json`.

A passing qualification result is evidence for later human/repository policy decisions. It is never itself an authority grant.

## Provider expansion

Additional providers may be bound only after their actual execution surface, cost class, capability and unattended state are independently verified in the actor/readiness/dispatch registries. A disabled or unverified provider must remain unavailable even if its nominal subscription would otherwise be included.
