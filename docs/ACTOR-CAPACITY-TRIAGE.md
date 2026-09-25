# Actor capacity and token-budget diagnostics

Use OneCompany's read-only diagnostic when a model works inside a Codespace
but a native lease or cloud worker reports "no budget":

```sh
python scripts/actor_capacity_report.py --actor mistral-vibe --capability implementation
python scripts/actor_capacity_report.py --actor grok-4-6-interactive --capability code_review
python scripts/actor_capacity_report.py --actor mistral-vibe --capability code_review --runtime-status TOKEN_BUDGET_EXCEEDED
```

**Three distinct questions:** (1) Does the versioned policy allow the actor's
cost class with no additional spending? (2) Did *that specific provider
execution* hit its token/turn limit, rate limit, actual account quota, or
authentication failure? (3) Is the specific OneCompany capability proven and
dispatchable under the correct lease and GitHub identity?

`financial_policy=ALLOWED_NO_ADDITIONAL_SPEND` means only that the existing
subscription is permitted by policy; it does not imply available provider quota.
`provider_quota=NOT_PROBED_BY_LEASE` is intentional. OneCompany must not infer
subscription balances from a Codespace, an API key, or an Actions-success badge.
`implementation_free_slots=0` and `capability_not_verified`/GitHub-access/
dispatch reasons mean **actor qualification** is blocked, not that additional
credits should be purchased. The diagnostic does not create authority, probe a
provider, consume tokens, activate Grok/Mistral, edit policies or admit a lease.

Observed 2026-09-25: OneCompany Mistral exact-head cloud review
[run 36144196913](https://github.com/NTinkicht/OneCompany/actions/runs/36144196913)
passed included-plan/PAYG-off preflight and started the model, then stderr
reported `Token limit exceeded: 61,256 > 50,000`. That is
`MODEL_EXECUTION_TOKEN_CEILING`, **not** provider quota exhaustion or
`FINANCIAL_POLICY_BLOCKED`. The protected-main workflow's `--max-tokens
50000` is changed to `64000` on PR #217, alongside wake's 75000→90000;
until that PR merges and the hosted path is rerun, Codespace behavior cannot
establish successful unattended review.

For Mistral native implementation, #133 and the canonical cloud WU must prove
a LOW-risk, scoped, lease-bound model-authored source-and-test commit and
independent review, **without** granting a model GitHub token. For Grok, #136,
#105, #172 require a distinct authenticated provider worker and separately
owner-authorized least-privilege GitHub publication; a read-only SuperGrok
routine is not a writer. Do not increase readiness or stream count based
solely on this diagnostic or a paid-provider workaround.
