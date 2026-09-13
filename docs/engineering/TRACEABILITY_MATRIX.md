# Traceability Matrix Operating Format

Minimum columns/fields:

| Source | Relationship | Target | Status | Evidence/SHA |
|---|---|---|---|---|
| FR-001 | requirement_to_acceptance_criterion | AC-001 | verified | TEST-001@sha |
| FR-001 | requirement_to_test | TEST-001 | pass | report@sha |
| RISK-001 | risk_to_mitigation | MIT-001 | implemented | diff@sha |
| MIT-001 | mitigation_to_test | TEST-002 | pass | report@sha |

The matrix is bidirectional: ask both `what verifies this requirement?` and `why does this code/test exist?`. Orphan detection is a gate, not a documentation cleanup task.
