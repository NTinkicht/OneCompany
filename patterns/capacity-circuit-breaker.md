# Pattern: Capacity / Spend Circuit Breaker

## Problem

Agent products expose many fallback paths: API credits, overage, auto-top-up, alternate paid models, hosted inference, or new vendors. A system that interprets “preferred worker unavailable” as “buy more capacity” cannot honor a fixed budget.

## Pattern

Capacity and spending are separate from capability.

An actor may be technically capable yet financially ineligible.

```text
candidate capability
  + configured permission
  + reviewer independence
  + live availability
  + budget eligibility
  = routable actor
```

If included capacity is exhausted, the state becomes `CAPACITY_DEGRADED`. Valid responses are:

- fail over to another already-authorized actor;
- use deterministic/local tooling;
- narrow/defer nonessential work;
- wait for an entitlement reset when no safe route exists;
- ask a human if a new spend decision is genuinely required.

It is **not** permission to enable paid fallback.

## Circuit-breaker properties

- separate booleans for paid fallback, overage, auto-top-up, and new paid vendor;
- fail closed when cost class is unknown;
- budget checked before execution, not after billing;
- no secrets added merely to reach a paid provider;
- routing preference changes do not rewrite financial policy.

## Generalized operating lesson

Epic encoded zero-extra-spend as a technical invariant and even added regressions against accidentally reintroducing forbidden provider routes. This turned a preference (“please don't spend more”) into enforceable operating policy.
