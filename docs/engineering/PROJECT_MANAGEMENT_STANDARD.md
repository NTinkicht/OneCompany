# Project Management Standard

OneCompany project management exists to maximize verified value flow, not ticket volume.

## Hierarchy

Objective/Epic -> measurable outcome -> dependency-ordered Work Units -> exact-SHA evidence -> release -> outcome review.

## Work Unit discipline

WUs are the smallest independently reviewable delivery increments. Each has one objective, explicit scope/non-goals, stable requirements/ACs, dependencies, risk, verification contract, owner/lease and completion evidence. Split units that cannot be reasoned about or reviewed safely.

## WIP and no-idle

Limit implementation WIP to preserve focus and canonical ownership. `No idle` means dependency-ready work must progress; it does not mean creating parallel speculative branches that violate the single-stream lease.

## Planning

Prioritize using value, urgency, risk reduction, dependency unlocking and effort. Estimates are forecasts, not commitments. Material uncertainty becomes discovery work before implementation.

## Change control

Scope changes during implementation require explicit impact analysis. A material change may return a WU from implementation to READY/design review. Requirements, tests and evidence are version-sensitive.

## Progress reporting

Report durable evidence: merged outcomes, current canonical WU/PR/SHA, gate state, blockers, residual risks, next dependency-ready work. Avoid vanity activity metrics such as prompts sent or lines generated.

## Retrospective learning

Incidents, escaped defects, repeated waivers, chronic flaky tests, architecture violations and failed estimates generate improvement actions. The operating system itself is allowed to evolve through governed changes.
