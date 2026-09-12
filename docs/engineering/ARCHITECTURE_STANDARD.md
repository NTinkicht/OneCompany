# Architecture and Design Standard

OneCompany does not impose a universal architecture. It requires a project to declare and defend the architecture appropriate to its context.

## Required properties

- System/module boundaries are explicit.
- Allowed dependency directions are explicit.
- Circular dependencies are forbidden unless a time-bounded migration waiver exists.
- Critical architecture rules become executable fitness functions when technically possible.
- Significant decisions receive ADRs.
- Architecture changes trigger requirements, risk, test and operations impact analysis.

## Architecture review

High-impact changes document context, alternatives, decision, trade-offs, security/privacy implications, data implications, operational consequences, migration and rollback.

## Design quality

Design review challenges cohesion, coupling, information hiding, interface contracts, failure semantics, idempotency, concurrency, data ownership, backward compatibility, observability and evolvability as applicable.

Patterns and principles such as SOLID, hexagonal architecture, DDD or microservices are tools, not universal laws. OneCompany blocks unjustified complexity as readily as poor separation.
