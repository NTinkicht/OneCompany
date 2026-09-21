# OneCompany Onboarding

OneCompany should feel like starting a company, not installing a pile of JSON files.

The primary entry point is intentionally one command:

```bash
python onecompany.py onboard --target .
```

It is **read-only by default**. Nothing is installed or overwritten.

## What onboarding detects

The assessor determines which situation you are in:

- `NEW_PROJECT` — empty/new repository;
- `ADOPT_EXISTING` — an existing product without OneCompany;
- `TEMPLATE_COPY` — a repository created from the OneCompany GitHub template but not initialized;
- `INSTALLED` — OneCompany is already installed;
- `SOURCE_REPOSITORY` — the OneCompany framework repository itself.

It also detects, where possible:

- GitHub repository and default branch;
- Python, Node/TypeScript, .NET, Java, Go, Rust, PHP or Ruby project signals;
- existing test directories;
- CI systems and GitHub Actions workflows;
- existing product/architecture/security/quality/design/operations contracts;
- path collisions with OneCompany framework files.

## Guided discovery: the first useful product conversation

The read-only `onboard` report now includes a `journey` projection for **Create** and **Adopt**.
The command shows the next step and three consequential questions in everyday language;
`--json` contains the complete draft. This is the beginning of the planned
Welcome → Discovery → Brief → Team → Build → Quality → Preview → Mission Control
experience, not a claim that the full UI or application runner exists.

The generated `product_brief_draft` reuses observed project/repository/stack/CI
facts, and **leaves the unknown audience, problem, first outcome and first feature
empty**. It never invents acceptance criteria or marks owner approval. The
three required product answers are: who uses it, what they should accomplish
first, and the smallest useful first feature. Privacy/data/accessibility/platform
constraints remain an explicit optional question.

A missing repository or a collision prevents apply exactly as before.
`journey.steps` and `next_action` describe a proposed workflow only:
`application_authorized=false`, `actor_qualified=false` and
`write_lease_granted=false` until the existing trusted OneCompany control plane
records actual evidence. Never use this JSON report as a lease, gate or authority.
Existing automated clients retain their prior assessment keys and `--apply`
semantics. It does not contact a provider or add AI spend.

## The safety contract

Assessment is non-mutating.

The report shows:

```text
mode
project/repository/default branch
stack
existing tests
existing CI
existing contracts
colliding framework paths
safe starting posture
blockers
next actions
```

OneCompany never silently overwrites a product-owned file during guided onboarding. A collision is a blocker that must be resolved deliberately.

## Apply the plan

After reviewing the assessment:

```bash
python onecompany.py onboard --target . --apply
```

Missing root contracts are initialized by default without replacing existing contracts. Use:

```bash
python onecompany.py onboard --target . --apply --no-contracts
```

when you do not want those starter contracts created.

If the GitHub remote is unavailable or ambiguous:

```bash
python onecompany.py onboard \
  --target . \
  --repository OWNER/REPO \
  --project-name "My Product" \
  --default-branch main
```

Machine-readable assessment:

```bash
python onecompany.py onboard --target . --json
```

## Safe defaults after adoption

A successful installation is **not autonomous by default**.

It starts with:

- autonomy `L1`;
- zero additional AI spend;
- all workers disabled/unconfigured;
- unattended dispatch disabled;
- ledger disabled until explicitly configured;
- supervision disabled / observe-only;
- no automatic risk acceptance;
- no automatic credential or budget expansion.

This allows OneCompany to be installed safely before authority is granted.

## New-project experience

Recommended path:

1. Create a repository from the OneCompany GitHub template **or** create an ordinary empty repository.
2. Run `python onecompany.py onboard --target .`.
3. Review the detected plan.
4. Run the same command with `--apply`.
5. Complete `PRODUCT.md`, then establish the first Objective/Epic/requirements/risks/WU.
6. Configure only the workers and permissions you actually have.
7. Run `doctor`, `validate`, `audit-github` and first-run acceptance drills.
8. Raise autonomy only through the explicit human decision process.

## Existing-project experience

OneCompany treats existing repositories as valuable systems, not blank templates.

1. Run the assessment first.
2. Review detected stack, CI, tests and collisions.
3. Resolve any naming/path conflict rather than overwriting existing assets.
4. Apply OneCompany.
5. Preserve the product's existing deterministic CI; OneCompany adds governance around it rather than replacing it.
6. Baseline existing technical debt instead of requiring an unrealistic rewrite.
7. Establish initial Objectives, requirements, risks and bounded Work Units around the current product.

## After onboarding

Use this readiness ladder:

```text
Installed
   ↓
Deterministic validation green
   ↓
GitHub protection configured
   ↓
Workers individually configured + smoke-tested
   ↓
Requirements/risk/traceability baseline exists
   ↓
One bounded WU completes under L1/L2
   ↓
Independent review / merge drills pass
   ↓
Scheduled supervision tested observe-only
   ↓
Human may deliberately raise autonomy
```

The goal is not to make activation difficult. The goal is to make every increase in authority **observable, reversible and earned by evidence**.

## Future product surface

The CLI is the dependency-light bootstrap experience. A future OneCompany Control Center / GitHub App may render the same contracts as a modern graphical experience: portfolio graph, company status, worker readiness, risk, WIP, gates and onboarding steps. The UI must remain a view/controller over the same versioned contracts rather than becoming a second source of truth.
