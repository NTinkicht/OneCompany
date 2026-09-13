# Pattern: Exact-Head Two-Key Gate

## Problem

AI review can become ceremonial: a reviewer approves an old commit, the author pushes another change, and the PR is merged because the conversation still says “looks good.” A second failure is self-gating: the same actor writes and certifies its own material work.

## Pattern

A merge candidate needs two independent keys on the **same exact SHA**:

1. **Deterministic key:** configured CI/tests/build/static checks are green.
2. **Judgment key:** an eligible independent non-author reviewer has reviewed that exact head and resolved required-severity findings.

The merge executor then uses expected-head protection so the merged head must still equal the gated SHA.

## Material authorship

Independence follows who materially produced the diff, not merely Git commit metadata. Failover, cherry-pick, replay, or bot commits must not launder authorship.

## Staleness rule

Any material code/test/governance commit after the verdict makes the final gate stale. Re-run the required gate on the new head.

## Why two keys

CI catches deterministic contract failures. Independent review catches missing tests, unsafe assumptions, architecture/security errors, and specification drift. Neither substitutes for the other.
