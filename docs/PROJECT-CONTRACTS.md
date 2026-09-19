# Project Foundation Contracts

OneCompany coordinates execution, but agents still need a stable definition of **what the product is allowed to become**.

Each installation needs authoritative product, architecture and security contracts before high autonomy; the core package must not supply a customer's domain decisions.

## Recommended contract map

Core templates live under `.onecompany/templates/contracts/`:

- `PRODUCT.md.template` → product problem, users, scope, journeys, success criteria;
- `ARCHITECTURE.md.template` → module/data/interface/concurrency boundaries;
- `SECURITY.md.template` → trust, auth, authorization, secrets, sensitive-data and abuse invariants;
- `QUALITY.md.template` → exact deterministic CI contract and test strategy;
- `OPERATIONS.md.template` → deployment, rollback, recovery, observability and production boundaries.

Run bootstrap with `--initialize-contracts` to copy missing templates to the target repository root. Existing files are never overwritten automatically.

## Authority order

A useful project-level hierarchy is:

```text
human-approved product/governance decision
    ↓
PRODUCT.md / ARCHITECTURE.md / SECURITY.md / QUALITY.md / OPERATIONS.md
    ↓
Work Unit acceptance contract
    ↓
implementation and tests
```

A Work Unit cannot silently contradict a higher-level contract. If the product/architecture/security contract needs to change, make that change explicit and review it as such.

## Keep contracts useful

Contracts should be concise enough that agents can retrieve relevant sections deterministically. Avoid turning them into historical diaries. Put rationale/history in ADRs, issues or retrospectives and keep the current invariant clear.

## Domain extensions

Projects may add contracts such as:

- `DATA-PRIVACY.md`;
- `API.md`;
- `MIGRATIONS.md`;
- `ACCESSIBILITY.md`;
- `LOCALIZATION.md`;
- `COMPLIANCE.md`;
- `MODEL-POLICY.md` for ML/AI products.

Only add a contract when it creates a durable decision boundary that workers need.
