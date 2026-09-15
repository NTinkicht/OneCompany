# Epic 0.6 A3b - Zero-spend unattended Actions adapter

A3b proves that OneCompany can start and reconcile a real unattended execution mechanism without creating authority, enabling paid fallback, or weakening protected-main governance.

## Activated worker

`onecompany-local` is a deterministic read-only worker executed by `.github/workflows/onecompany-local-readonly.yml` on a standard GitHub-hosted Ubuntu runner. Its only verified capability is `repository_intelligence`.

The worker receives only `contents: read` and `actions: read`. Checkout uses `persist-credentials: false`. The workflow revalidates that the repository is public and that OneCompany's zero-extra-spend controls remain asserted before doing any work.

Live feature-branch proof:

- workflow run: `35026542482`
- exact head: `3a0d2571ad9e655ff3b130f10fd787703f74f603`
- conclusion: `success`
- run URL: `https://github.com/NTinkicht/OneCompany/actions/runs/35026542482`

The production adapter `scripts/local_actions_adapter.py` revalidates the public-repository property and zero-spend policy, reconciles an existing provider run before dispatch, invokes only the reviewed workflow on `main`, and refuses to report `DISPATCH_STARTED` until a GitHub Actions run ID and URL are observed.

## Authority boundary

The worker has no implementation capability, no implementation capacity, no repository write permission, no review or merge authority, and no lease authority. `dispatch.py` therefore cannot resolve it for `implementation` or `ci_remediation`. Durable unattended write authority remains deferred to B1 and the canonical ledger/lease policy.

## Copilot capacity probe

A bounded Copilot CLI workflow was also tested using GitHub's built-in short-lived `GITHUB_TOKEN`, `contents: read`, `actions: read`, `copilot-requests: write`, pinned Copilot CLI `1.0.83`, read-only tools only, and the CLI's minimum accepted `--max-ai-credits=30` bound.

Authentication, GitHub permissions, CLI installation, zero-spend preflight, and the read-only tool sandbox succeeded. The provider then returned `monthly quota exceeded` before a model response; the run reported `0 Premium` requests. Consequently:

- `github-copilot` remains disabled and unconfigured;
- Copilot readiness remains `not_started` and unattended verification remains false;
- `copilot-actions-readonly` remains configured false;
- no credits, top-ups, overage, PAT, API key, PAYG provider, or paid fallback was added.

Copilot can be re-evaluated later when included capacity resets, but its dormant adapter cannot currently be routed.

## Idempotency

A3a's local execution journal remains the caller-side replay guard. A3b adds a provider-side guard as well:

1. the adapter searches the target workflow's existing `workflow_dispatch` runs for the deterministic dispatch title before sending a POST;
2. the workflow has a concurrency group keyed by the same dispatch identity;
3. a duplicate workflow-dispatch run rechecks prior runs and skips duplicate execution.

The GitHub Actions run is execution evidence only. It does not grant coordination or lease authority.
