# Traceability Standard

OneCompany requires bidirectional traceability. Traceability exists to prove that requested behaviour is implemented and verified, and that implementation/tests have a justified source.

## Required chain

Objective -> Requirement -> Acceptance Criterion -> Work Unit -> Design/Architecture -> Test -> Evidence

Risk -> Mitigation -> Verification Test -> Evidence

Change -> Impacted Requirement/Risk/Test/Documentation

## Rules

- Every approved requirement belongs to a business/user objective or explicit constraint.
- Every implemented requirement has at least one acceptance criterion.
- Every acceptance criterion has verification evidence before DONE.
- Every high/critical risk mitigation has verification evidence before merge.
- Every test should trace to a requirement, risk, regression defect or quality fitness function; truly exploratory tests may be marked exploratory.
- Evidence records the exact commit SHA.
- A head change invalidates merge-ready evidence until the affected gates are rerun or explicitly proven unaffected.

## Matrix

A project may store the matrix as JSON/CSV/database, but OneCompany's semantic model is stable: source ID, target type, target ID, relationship, verification state, evidence URI/SHA.

Coverage percentages never replace traceability. 100% line coverage can still leave an acceptance criterion unverified.
