# Failover Example

A WU is on branch `wu29-consent-aware-dispatch-suppression`, PR #174.

1. Preferred implementer reaches capacity limit.
2. Orchestrator reconciles current exact head.
3. Existing worker's implementation lease is released due to `quota_exhausted`.
4. Replacement writer receives the **same branch and PR**, not a new stream.
5. Replacement continues from current exact head and preserves prior material authorship.
6. CI reports only formatting failure.
7. Several manual formatting guesses fail; the company recognizes an execution-environment mismatch.
8. Lease fails over to an actor that can run the repository-pinned Prettier tool.
9. New commit invalidates any earlier final gate.
10. CI must become green, then an eligible non-author reviewer confirms the new exact SHA.
11. Merge executor verifies head == approved SHA before merge.

The lesson is not “use a particular AI.” The lesson is: **preserve the stream, change the worker, use evidence, and re-gate exact heads.**
