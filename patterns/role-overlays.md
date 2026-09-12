# Pattern: Actor + Role Overlay

## Problem

Generic agents benefit from specialist instructions, but turning every specialist prompt into a “new employee” corrupts authorship, capacity, reviewer independence, and permissions.

## Pattern

Separate **actor identity** from **professional lens**.

- **Actor:** a real model/tool/human identity with capacity, execution path, permissions, cost class, material authorship, and review eligibility.
- **Role overlay:** a bounded set of specialist questions and deliverables applied to an actor for one Work Unit.

Example:

```text
actor: claude
overlay: security-reviewer
role lease: independent_reviewer
```

The overlay makes the review more focused. It does not create a second Claude, another reviewer, or additional independence.

## Hard rules

An overlay never creates:

- actor identity or capacity;
- an implementation lease;
- repository credentials or permissions;
- reviewer independence;
- merge authority;
- permission to violate budget/security policy.

## Selection

Choose the **smallest useful overlay set**. One primary overlay is normally enough. Add a secondary advisory overlay only when it asks a genuinely orthogonal question.

Examples:

- backend implementation → `backend-architect`;
- migration/concurrency review → `database-reliability`;
- exact-head binding review → `code-reviewer`;
- auth/privacy change → `security-reviewer`;
- deployment/recovery work → `sre`;
- user workflow → `persona-walkthrough`.

## Provenance

Tabibi operationalized this pattern from a curated subset of `NTinkicht/agency-agents` pinned at commit `647c8baa42b6842afb4a97bf2c0950d45ba88e8b`. OneCompany keeps the concept and governance separation, with new concise overlay files under `overlays/`.
