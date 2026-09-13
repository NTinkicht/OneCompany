# Testing and QA Standard

Testing demonstrates properties of the product; it does not merely increase a coverage number.

## Families

OneCompany recognizes static analysis, unit, component, integration, contract, API, E2E, acceptance, regression, property-based, fuzz, mutation, security, data/migration, performance, reliability/chaos, accessibility, visual regression, compatibility, operations and AI-evaluation testing.

The Work Unit risk level and impacted domains select the mandatory families.

## Coverage

Default Production thresholds are 85% line, 80% branch and 95% changed-line coverage. High Assurance raises these defaults. Coverage cannot decrease below an adopted baseline without waiver.

Critical behaviour is judged by scenario coverage and traceability, not percentage alone.

## Test quality

Mutation testing is used where supported to measure whether tests detect meaningful behavioural changes. Production defaults target a 70% mutation score; High Assurance targets 80%. Projects may tailor thresholds with rationale.

Tests must be deterministic, isolated at the appropriate layer and explicit about failure. A flaky test cannot be hidden by arbitrary retries. Quarantine requires an issue, owner, reason and expiry.

## Independence

Medium/high-risk Work Units should have independent test-design challenge. The implementer writes implementation-level tests but should not be the only mind deciding what correctness means.

## Escaped defects

Every confirmed escaped defect creates a regression artifact or an explicit engineering learning action before closure.
