# Risk Assessment and Treatment Standard

Risk management begins before implementation and continues through release and operation.

## Risk statement

Use cause-event-consequence form:

`Because <cause>, <event> may occur, resulting in <consequence>.`

This is more actionable than vague entries such as `security risk`.

## Scoring

Likelihood and impact are scored 1-5; inherent score = likelihood x impact. Treatment is avoid, reduce, transfer or accept. After treatment, residual likelihood/impact are rescored. Scores guide attention; domain-specific severity can override arithmetic where safety/security/privacy requires it.

Bands: 1-4 low, 5-9 medium, 10-16 high, 17-25 critical.

## Required risk domains

Evaluate applicable product, requirements, architecture, security, privacy, safety, data, delivery, operations, reliability, performance, compliance, financial, vendor, AI-model, reputation and accessibility risks.

## Governance

Every open risk has an owner and review trigger. High residual risks require an explicit owner and visible treatment. Critical residual risks require human acceptance. Security, privacy and safety risks are never silently accepted by an autonomous actor.

Scope, requirement, architecture, dependency or threat-model changes trigger reassessment.

## Test selection

Risk determines required test families. The test plan must demonstrate how each significant mitigation will be verified. Risk controls without tests or other objective verification are incomplete controls.
