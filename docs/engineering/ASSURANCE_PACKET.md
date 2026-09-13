# Work Unit Assurance Packet

The assurance packet is the machine-readable contract joining requirements, acceptance criteria, risks, mitigations, design, tests and exact-head evidence for one Work Unit.

## Before implementation

The packet proves readiness: requirements are approved and objectively verifiable; acceptance criteria exist; risk has been assessed; required test families are selected from risk; architecture/documentation/release impacts are declared; traceability reaches from objective to planned verification.

## At merge-ready

The packet becomes evidence, not a plan. It must identify the 40-hex candidate SHA, verified requirements and ACs, quantitative coverage/mutation results for code-changing work, PASS evidence for every risk-required test family, test-to-evidence trace links, all mandatory quality gates, and an independent non-author review of the exact same candidate SHA.

`python onecompany.py assurance <packet.json>` is the authoritative dependency-free gate. `trace`, `risk` and `evidence` are reporting views; they do not replace the gate.

## No-code changes

Set `code_change` to false only when the candidate genuinely changes no executable code. Quantitative source-code coverage gates are then not applicable, but requirements, traceability, risk, documentation, review and other relevant evidence remain required.

## Waivers

A missing required assurance dimension cannot be converted to N/A informally. Use an explicit expiring waiver when policy permits it. Security/privacy/safety and critical residual-risk rules retain their human-approval boundaries.
