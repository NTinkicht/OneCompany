# Phase 1 harness boundary — ONE existing Execution Core

Status: **foundational admission contract, not a live multi-provider deployment**.
Implements the bounded groundwork of [#141](https://github.com/NTinkicht/OneCompany/issues/141) / `WU-P1-FOUNDATIONS-001`.

The existing `scripts/execution_core.py` owns `RunKey(wu_id, run_id, generation)`,
the journal, stall/resource guards and `AgentRuntimeAdapter`. There is **no**
second orchestrator. `scripts/harness_contract.py` is a pure advisory admission
check for a potential worker invocation under the already-authorized native
lease. It makes **no network call or filesystem mutation**, does not create a
lease and cannot approve a PR, widen autonomy or merge. Call it only after the
trusted parent has queried and verified the actual live ledger, current PR and
head/base, relevant actor readiness and zero-spend budget; model content,
GitHub issue prose and local `state.json` are **not** trusted inputs.

## Two inputs — never conflate them

- `HarnessIntent`: a requested RunKey, tenant/project, actor/capability,
  exact head/base, bounded tool list and optional provider seam. All candidate
  fields are untrusted.
- `TrustedHarnessSnapshot`: the same exact identity *derived by a trusted
  parent* from live authoritative systems, a live canonical implementation
  lease, enabled actor capability, policy-allowed tool subset, emergency-stop
  state, USD 0 extra-spend posture and provider availability. Constructing this
  Python dataclass by itself **does not certify the sources**.

`assess_intent` fails closed on mismatched WU/run/generation, project, actor,
capability, base/head, missing active lease, emergency stop, unverified actor,
unsupported cost class, overage request, unknown tool scope, prohibited
governance tool or unavailable provider. A result of
`ADMITTED_FOR_TRUSTED_PARENT` says **only** that request fields match the
supplied trusted snapshot. Revalidate the true lease and PR/RunKey immediately
before any eventual external side effect.

## Phase 2 providers are planned, not enabled

The non-authoritative `provider_seam` contract reserves conceptual names:
native, memory, context, model_endpoint, runtime_capability, workspace,
ui_assurance, telemetry, skill and deployment. The chosen concrete backend
(for example OpenViking or Supermemory behind memory/context, KServe behind
model_endpoint and ARTEMIS behind ui_assurance) requires later exact-version
licensing, tenancy, secrets and budget review and a measured zero-extra-cost
pilot. These names never become new identities, workers, leases or authorities.
An optional provider outage blocks that optional request, without switching
to PAYG or modifying the native `RunKey`.

Next: connect the contract to a trusted Execution Core adapter only when it can
provide live snapshots and deterministic evidence of its own. Then qualify
one complete new/adopt → canonical WU → test → independent non-author review →
eligible merge → preview slice, with source L1 intact until explicit reviewed
authorization to change it.
