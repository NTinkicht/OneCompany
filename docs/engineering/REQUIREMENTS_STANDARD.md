# Requirements Engineering Standard

Requirements are executable governance inputs, not prose written once and forgotten.

## Requirement hierarchy

Use stable IDs: BR (business), UR (user), FR (functional), NFR (non-functional), SEC, DATA, OPS, UX and CON (constraint). A Work Unit must trace to one or more approved requirements.

## Requirement quality gate

A requirement must be necessary, implementation-free at the appropriate abstraction level, unambiguous, complete, singular, feasible, verifiable, correct, conforming and traceable. A requirement that fails these qualities does not enter implementation.

Prefer one normative obligation per requirement. Use **shall** for binding requirements. Avoid subjective words such as `fast`, `easy`, `user-friendly`, `robust`, `appropriate`, `sufficient`, `normal`, `as needed`, `and/or`, and `etc.` unless objectively defined.

Bad: `The dashboard shall load quickly and be user friendly.`

Better: `NFR-014: The dashboard shall render its primary interactive content within 2.0 seconds at the 95th percentile under the PERF-BASE workload.`

## Mandatory metadata

Every requirement records rationale, source, priority, lifecycle status, verification method, acceptance criteria and related risks. Non-functional requirements additionally record a measurable target, measurement method and operating conditions.

## Acceptance criteria

Acceptance criteria are observable outcomes, not implementation tasks. They use stable AC IDs. Edge, negative and failure behaviour must be represented when relevant.

## Change control

Changing a baselined requirement triggers impact analysis across design, architecture, risks, tests, documentation and release evidence. Evidence for an old requirement revision cannot silently remain merge-valid.

## Definition of Ready

A Work Unit is not READY unless its objective, scope/non-goals, requirements, acceptance criteria, dependencies, risks, test strategy, architecture impact, data/security/privacy/UX/operations impacts and evidence expectations are known to the level warranted by risk.
