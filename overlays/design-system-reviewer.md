# Overlay: Design System & Experience Reviewer

## Lens

Review user-facing changes for coherence, state completeness, accessibility, responsive behavior, localization readiness, performance and maintainability without dictating a framework.

## Ask

- Does the change reuse canonical tokens/components and interaction patterns?
- Are loading, empty, validation, success, degraded, permission and error/recovery states complete where relevant?
- Are semantics, accessible names, keyboard/focus, contrast and motion behavior sound?
- Does the surface survive narrow/wide viewports, long content, localization and RTL where applicable?
- Are destructive actions explicit and recoverable where possible?
- Is visual/interaction regression evidence deterministic and intentionally reviewed?
- Does polish introduce duplication, brittle CSS, inaccessible custom controls or excessive performance cost?

## Expected artifact

A bounded experience review with concrete findings and the smallest useful evidence: deterministic test references, screenshots/diffs, keyboard walkthrough, responsive/localization matrix, accessibility findings or performance evidence.

## Not authority

This overlay does not create a reviewer identity or merge authority. Binding review still requires an eligible independent actor under the exact-head policy.
