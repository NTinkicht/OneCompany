# Gemma 4 hosted-free qualification — one-shot canary

Parent: #218. This lane is a **synthetic, public-data-only API canary**. It does
not make Gemma an autonomous coder/reviewer, give the model a GitHub token,
execute generated source or permit a merge. It is the first measurable gate
before any guarded canonical Work Unit.

## Provider vs runtime

Google Antigravity SDK's LiteRT configuration runs Gemma on local hardware.
This canary instead calls the separate hosted OpenRouter API directly via
Python's standard library. It does **not** run the Antigravity SDK, claim
unlimited free usage or require a GPU.

The *only* accepted model ID is
`google/gemma-4-26b-a4b-it:free`. No `openrouter/free`, fallback list,
auto-router, paid sibling or second attempt. One API call only when live
invocation was explicitly selected. OpenRouter's free-tier request/day limit
and provider uptime may interrupt the worker. A failure is reported, not
silently replaced by a paid call.

## Safe first test

1. Review and merge this PR under the existing exact-head CI and independent
   final-head review rules.
2. On protected main, run the **OneCompany Gemma Free Synthetic Probe** GitHub
   workflow with `live=false`. The offline tests and machine budget preflight
   require **no credential** and make no provider request.
3. To test genuine hosted Gemma inference, the repository owner creates an
   OpenRouter API key with no new purchase or credit/top-up and adds it as the
   GitHub Actions repository secret **OPENROUTER_API_KEY**. Never paste keys into
   an issue, PR, log, chat, or committed config. Only the owner authorizes and
   manages external account access and credentials.
4. Owner dispatches the same workflow with `live=true`. One synthetic
   clamp-function plus unittest request is sent to the exact free model. The
   job reports status, code/test byte counts and hashes; **not** the source,
   secret or request/response payload. Generated code is parsed with Python
   `ast` and **never executed**. Provider error (including quota HTTP 429)
   fails closed.
5. Inspect the actual run outcome, provider usage and account data-handling
   policy. This is not independent review or material authorship evidence.
   A full provider-authored real WU and exact-head independent reviewer pilot
   require separate trusted scope/lease/commit/review work under #218/#215.

Before exposing any private repo code or credentials, determine whether the
specific free-provider route stores prompts, permits training, or retains
content, and require project-specific authorization. The synthetic task in
this canary sends **no repository code**.

The trusted `.onecompany/budget.json` must remain zero-additional-spend with
no paid fallback, overage, auto-topup or new paid vendor. Runner costs must
remain included/free. An absent secret leaves the offline test useful but
means live inference is **not tested**.

## Reference

- OpenRouter free endpoint:
  https://openrouter.ai/google/gemma-4-26b-a4b-it%3Afree
- OpenRouter free-tier pricing/limits: https://openrouter.ai/pricing/
- Google's *distinct* local LiteRT-Antigravity route:
  https://antigravity.google/docs/sdk/local-models/
