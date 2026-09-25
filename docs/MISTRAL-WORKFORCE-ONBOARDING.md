# Mistral autonomous workforce onboarding — protected-main source lane

The owner can delegate **technical coding, deterministic test authorship and
independent review** to Mistral while preserving OneCompany's native leases,
zero-additional-spend boundary, scoped writes and non-self final gate.

This repository already has a source-only `MISTRAL_WORK_V1` implementation
workflow: an included-entitlement GitHub runner with a trusted parent validates
the exact canonical PR, protected-main queue scope, active durable Mistral
implementation lease, source changes and model-produced tests. The parent
publishes a non-force exact-parent commit, then triggers CI. No model GitHub
token, paid model or Codespace is needed for that lane.

The new `MISTRAL_START_V1` intake addresses the **pre-PR circularity**: its
trusted parent prepares one draft PR on the reserved canonical WU branch.
It is only allowed when a LOW/MEDIUM WU is READY in protected-main queue,
the WU branch is unused, PR number is still null, an in-scope Python test
path does not exist, dependencies are done, main matches the owner-pinned SHA,
the USD0 budget is intact, and emergency stop is clear.

## Owner invocation on existing issue #130

```text
@mistral-vibe
MISTRAL_START_V1
work_unit: WU-CLOUD-MISTRAL-DEV-001
main_sha: <CURRENT_40_HEX_PROTECTED_MAIN_SHA>
```

GitHub Actions must have **Allow GitHub Actions to create and approve pull
requests** enabled for this repository; only the owner may change this GitHub
setting. Without it the source-only runner reports a failure, not a fake PR.

The created PR's sole stub is explicitly attributed `onecompany-local`;
**it is not a model-authored change or verified tests**. The runner does not
admit a lease or activate writer capacity. The generated PR number must be
bound to the same WU in protected queue through an independently reviewed
control-plane PR. Then a genuine, scoped Mistral implementation lease may be
admitted once the actor's live writer-capacity qualification exists; invoke
the already-shipped `MISTRAL_WORK_V1` with that exact WU/PR/branch/head/base
and lease ID. A fresh deterministic validation must check the *model-authored*
commit; an independent non-Mistral actor must review it. No self-approval.

A completed source-only Mistral one-shot review of PR #220 is recorded in
Actions 36152811616. PR #222 proposes binding PASS/FAIL review publication,
but does not retroactively make an older `COMMENTED` advisory review into an
approved gate. Neither a stub draft PR nor source-code availability elevates
`.onecompany/readiness.json` to one verified implementation stream. Qualify
the scoped actual model-produced source/tests and publisher before switching
capacity from zero.
