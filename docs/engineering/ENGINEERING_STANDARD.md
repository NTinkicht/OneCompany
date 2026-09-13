# OneCompany Engineering Standard (OCES)

OCES is the default engineering assurance model for OneCompany projects. It converts engineering quality from advice into evidence-backed gates.

## Core rule

**No artifact is considered correct because an AI or human says it is. The claim must be supported by reproducible evidence appropriate to its risk.**

OCES covers the full lifecycle: requirements, traceability, risk, design, architecture, implementation, verification, documentation, release and learning from production.

## Standards inspiration

OCES is informed by ISO/IEC/IEEE 29148 requirements engineering, ISO 31000 risk management, ISO/IEC 25010 product quality and OWASP ASVS for application security. OneCompany does not claim certification or full conformance merely by using these policies.

## Eight assurance gates

1. Q0 Ready — requirements, acceptance criteria, dependencies and risks are sufficiently defined.
2. Q1 Design — solution, data/API/UX behaviour, failure modes and alternatives are understood.
3. Q2 Architecture — declared boundaries and fitness functions remain valid.
4. Q3 Code Quality — deterministic static quality checks pass.
5. Q4 Functional QA — required functional test families pass.
6. Q5 Non-functional QA — risk-selected security, reliability, performance, accessibility and compatibility checks pass.
7. Q6 Docs/Ops — documentation, observability, migration, rollback and operational readiness are synchronized.
8. Q7 Independent Exact-Head Gate — a non-author reviewer evaluates the exact merge SHA and all evidence is current.
9. Q8 Release — the built artifact is traceable to the approved SHA and release verification passes.

A lower gate cannot be waived implicitly by success at a later gate.

## Quality profiles

Prototype, Standard, Production, High Assurance and Regulated profiles control default thresholds. Autonomy and quality are orthogonal: L5 autonomy never means lower assurance.

## Risk-based tailoring

The Work Unit risk level determines mandatory evidence. Low-risk documentation work should not launch expensive load tests. Authentication, data loss, privacy, safety and critical business changes receive substantially stronger verification.

## Debt ratchet

Existing debt may be baselined during adoption. New debt is forbidden unless an explicit, expiring waiver exists. Touched code must not worsen the baseline. This allows legacy projects to adopt OCES without pretending existing debt does not exist.

## Learning rule

Every escaped defect must result in at least one of: a regression test, a new architecture/quality fitness function, a requirement clarification, a risk-control improvement, or a documented reason why none applies.
