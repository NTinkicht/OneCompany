# Pattern: Orthogonal Parallelism

## Problem

“No idle agents” can degenerate into “everyone edits something.” That maximizes collisions rather than throughput.

## Pattern

Only one worker owns implementation for a bounded WU. Other available capacity may work on **orthogonal artifacts** that do not compete with the canonical implementation stream.

Useful lanes include:

- architecture/risk map;
- security/privacy threat review;
- test matrix and adversarial cases;
- repository/blast-radius scouting;
- failure/retry/concurrency analysis;
- documentation;
- observability/readiness;
- backlog decomposition;
- research;
- retrospective/incident analysis.

A specialist finding that requires code is handed to the active implementer unless that specialist receives an explicit implementation lease.

## Guardrail

Parallelism is justified by different questions or artifacts, not by reviewer count. Multiple generic reviews of the same thing are usually activity theater.

## Relationship to no-idle

OneCompany optimizes useful progress, not utilization percentage. It is valid for a specialist to be idle when no safe orthogonal task exists.
