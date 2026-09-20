# OneCompany Roadmap

> **2026-09-20 trajectory change:** The [Master Evolution Roadmap](MASTER-EVOLUTION-ROADMAP-2026.md) and [external capability register](../.onecompany/external-capability-register.json) are the current strategic target and Phase 0 coverage baseline (tracked by #123). This older CLI/provider-layer sketch remains historical context, not an alternative roadmap. Proposed future WUs are not admitted implementation leases; preserve existing portable factory and Execution Core.

The repository already defines a usable file-based control plane. Future product layers should preserve the same contracts.

## Foundation — current

- constitution and operating model;
- machine-readable config/actors/roles/budget/state/queue;
- validation, routing, lease, simulation, bootstrap helpers;
- worker adapters;
- GitHub templates and safe validation workflow;
- migration, security, incident, no-idle and review guidance.

## Next: CLI

Target experience:

```bash
onecompany init
onecompany doctor
onecompany validate
onecompany route --role implementer
onecompany lease acquire ...
onecompany reconcile
onecompany status
onecompany simulate
```

Interactive `init` should ask about repository, CI, available subscriptions/workers, spend cap, sensitive data, and autonomy level, then generate safe defaults.

## Next: provider adapters

Optional adapters should detect capability/availability without putting vendor logic into the constitution. Examples: GitHub-native agents, local CLIs, Slack attention layer, CI systems beyond GitHub Actions.

## Next: GitHub App / control center

Potential features:

- live WU/lease/gate visualization;
- stale-gate detection;
- no-idle alerts;
- budget/capacity dashboard;
- failover suggestions;
- immutable decision/audit timeline;
- one-click lower-autonomy/stop.

## Next: policy engine

Move universal invariants from Python checks into versioned, testable policy modules while keeping a dependency-light bootstrap path.

## Next: benchmark/simulation suite

Create reproducible scenarios for duplicate writers, stale reviews, CI failures, prompt injection, budget escalation, provider outage, merge races, and state drift.

## Principle for every roadmap item

Never make the product more autonomous by making its authority less explicit.
