# Pattern: Single Canonical Stream + Explicit Lease

## Problem

A multi-agent system can easily produce two “helpful” implementations for the same task. That increases merge conflicts, review cost, context drift, and the chance that the wrong branch is merged.

## Pattern

For each bounded Work Unit:

- exactly one canonical issue/contract;
- exactly one canonical implementation branch/PR;
- exactly one active implementation lease;
- one current exact head;
- failover changes the worker, not the stream.

The lease records who may materially modify the stream now. It is not inferred from a comment, assignment, or heartbeat.

## Failover

A valid handoff preserves:

- WU/objective;
- branch and PR;
- current head;
- acceptance criteria;
- authorship history;
- unresolved findings;
- budget/security constraints.

The replacement must have a concrete executable path. “Assigned to X” is not a completed handoff if X cannot actually run.

## Why it works

This is essentially a single-writer discipline applied to autonomous delivery. It makes ownership, history, and merge intent unambiguous while still allowing many read-only or advisory workers in parallel.
