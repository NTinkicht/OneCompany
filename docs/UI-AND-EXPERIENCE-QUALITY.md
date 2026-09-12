# UI and Experience Quality

OneCompany should help autonomous teams ship products that are not merely functional, but coherent, accessible, responsive and maintainable. It does this with **evidence requirements**, not a mandated frontend stack.

## The rule

If a Work Unit changes a user-facing surface, its verification contract must include the experience risks actually introduced by the change.

A form change may need keyboard, validation and error-state evidence. A dashboard redesign may need responsive, accessibility and visual-regression evidence. A backend-only migration needs none of those unless it changes observable UX.

## Default quality model

### 1. Design-system consistency

Prefer canonical tokens and reusable components over isolated CSS/markup. A new variant should have a reason to exist. Duplication is not a design system.

### 2. State completeness

Happy-path screenshots are insufficient. Review applicable loading, empty, no-results, success, validation, degraded, permission-denied, offline/retry, error/recovery and destructive-action states.

### 3. Accessibility

For web projects, OneCompany recommends WCAG 2.2 Level AA as the default target unless product/legal policy says otherwise. Automated scanners catch only part of the problem; important journeys still need semantic, keyboard/focus and task-level review.

Reference: https://www.w3.org/WAI/standards-guidelines/wcag/

### 4. Responsive and international

Test the project's actual device matrix. Where localization exists or is planned, include long strings and locale formatting. Where RTL languages are relevant, use logical direction-aware layouts and test real RTL fixtures rather than assuming mirroring works.

### 5. Visual regression

Use deterministic screenshot/visual regression when it adds signal and can be run within project budget. Pin fonts/browser/runtime where possible, disable nondeterministic animation/data, and review baseline changes intentionally.

OneCompany does not require Storybook, Chromatic, Playwright, Cypress or any other specific tool. Existing stack-native or free/local tools are valid.

### 6. Performance

Define budgets around meaningful journeys. Web projects may use Core Web Vitals and project-specific bundle/network/render budgets; native/desktop projects should use equivalent interaction/startup/resource metrics. Performance checks that are too noisy to be deterministic should inform review rather than become a retry-until-green gate.

### 7. Evidence proportionality

Do not make invisible changes produce fake screenshots. Do not make a major interaction redesign pass with only unit tests. The Work Unit's risk class and changed surface determine the evidence.

## Autonomous reviewer questions

A design/experience reviewer should ask:

- Is the hierarchy immediately understandable?
- Does it reuse the design system rather than introduce one-off patterns?
- Are all important states represented and recoverable?
- Can keyboard/screen-reader users complete the journey?
- Does it survive narrow/wide screens and long/localized content?
- Is destructive behavior unmistakable and recoverable where possible?
- Did the change create layout shift, slow interaction or unnecessary asset cost?
- Are screenshots/visual baselines stable and intentionally approved?
- Does the implementation remain maintainable, or did visual polish create architectural debt?

## Deterministic CI examples

Projects can choose a subset appropriate to their stack:

```text
component interaction tests
browser journey tests
automated accessibility checks
visual snapshot/screenshot diff
responsive viewport fixtures
RTL/localization fixture run
bundle/performance budget
```

The selected commands belong in `QUALITY.md`; experience invariants belong in `DESIGN.md`.
