# Pattern: Shadow Before Authority

## Problem

A promising tool can look good on benchmarks yet omit exactly the fact that changes a merge, security, or recovery decision. Giving new infrastructure authority immediately makes experimentation a production risk.

## Pattern

Run the candidate beside the authoritative path first.

```text
authoritative evidence -> normal decision
          \
           -> experimental/shadow transform -> compare result/metrics
```

The shadow output may inform evaluation but cannot control the decision until explicit graduation criteria are met.

## Graduation criteria

Define them before the trial. Typical criteria:

- useful reduction in cost/context/latency;
- no missed blocker/major fact in representative samples;
- no incorrect merge/security decision caused by omission;
- reliable fallback to original evidence;
- acceptable latency and operational stability;
- pinned/provenance-verified implementation;
- explicit reviewed promotion decision.

## Reset rule

A serious omission in a high-risk domain resets the relevant graduation claim. Do not average away catastrophic misses with a good aggregate compression percentage.

## Generic evaluation example

A candidate context compressor runs read-only beside original evidence. Original evidence remains authoritative, sensitive material is excluded, and the experimental component cannot rewrite governance files or become a merge/security authority.

This pattern generalizes to new agents, reviewers, routers, summarizers, test generators, and model upgrades.
