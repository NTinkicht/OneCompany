# Budget and Capacity Governance

Autonomous systems can accidentally turn a temporary quota problem into an unbounded bill. OneCompany treats financial constraints as executable policy.

## Budget classes

Actors/integrations should be classified as:

- `INCLUDED_SUBSCRIPTION` — already paid fixed plan;
- `FREE_ALLOWANCE` — free quota with known/unknown limits;
- `LOCAL` — local compute, no provider usage fee;
- `METERED_ALLOWED` — per-use cost explicitly permitted inside cap;
- `METERED_FORBIDDEN` — technically available but policy forbids spend;
- `UNKNOWN_COST` — conservative handling required.

## Zero-extra-spend mode

Recommended policy for users who already pay subscriptions but want no additional billing:

```json
{
  "additional_monthly_ai_spend": 0,
  "allow_paid_fallback": false,
  "allow_overage": false,
  "allow_auto_topup": false,
  "allow_new_paid_vendor": false,
  "unknown_cost_behavior": "forbid"
}
```

Subscription actors are usable within their included capacity. When quota is exhausted, route to another included/free/local actor or enter `CAPACITY_BLOCKED`.

## Capacity is dynamic

The router should consider:

- quota exhausted until reset;
- temporary rate limiting;
- context-window constraints;
- code-review-specific limits separate from general chat limits;
- GitHub runner availability;
- local machine availability;
- service outages;
- permission/tool availability.

An actor can be eligible for planning but unavailable for GitHub code review, for example.

## Headroom signals

A project may track approximate headroom to improve routing, but should avoid brittle dependence on private/undocumented quota endpoints. Treat headroom as a hint unless authoritative.

## Spend approval

Any action that can newly incur money should identify:

```text
vendor
billing mechanism
maximum expected amount
recurrence/one-time
what happens after cap
who approved it
```

No unattended worker should click/enable top-ups, paid overage, credits, subscriptions, or new vendors unless explicit policy delegates that exact class of purchase.

## GitHub Actions cost

Private repositories may consume included/paid Actions minutes. “No AI spend” is not necessarily “no infrastructure spend.” Projects should separately declare CI/runner budget and schedule frequency.

Avoid aggressive scheduled watchdog workflows in private repos unless the owner accepts runner cost. Event-driven checks are usually cheaper.

## Cost-aware degradation

When constrained:

1. preserve correctness/security gates;
2. reduce redundant review/analysis;
3. use deterministic/local tooling first;
4. route read-only reconnaissance to cheaper/included actors;
5. postpone noncritical work;
6. never weaken safety checks merely to save tokens without explicit policy.
