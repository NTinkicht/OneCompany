# Documentation Standard

Documentation is part of the deliverable and must remain synchronized with behaviour.

Every Work Unit declares documentation impact: none, user, developer, API, architecture/ADR, security, operations/runbook, configuration, migration, release notes or training.

Public APIs and externally meaningful configuration require reference documentation. Operationally meaningful changes require runbook/observability updates. Breaking changes require migration instructions. Architectural decisions require ADRs when significant.

Code comments should explain intent, constraints and non-obvious trade-offs rather than narrating obvious syntax.

Examples should be executable or automatically checked where feasible. Broken links and stale generated documentation are quality failures, not cosmetic issues.
