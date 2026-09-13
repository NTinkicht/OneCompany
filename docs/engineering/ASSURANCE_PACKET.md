# Work Unit Assurance Packet

The assurance packet is the machine-readable contract joining requirements, acceptance criteria, risks, mitigations, design, tests and exact-head evidence for one Work Unit.

## Before implementation

The packet proves readiness: requirements are approved and objectively verifiable; acceptance criteria exist; risk has been assessed; required test families are selected from risk; architecture/documentation/release impacts are declared; traceability reaches from objective to planned verification.

Requirement statements use one `shall` obligation, avoid configured ambiguous language, carry the correct typed ID, and link to real acceptance criteria, risks, the owning Work Unit, design/architecture and planned tests. Non-functional requirements additionally carry a measurable metric, target, method and conditions.

Traceability is referentially checked rather than accepted as prose: requirement-to-test links must name real tests; requirement-to-WU links must target the packet's WU; risk-to-mitigation and mitigation-to-test links must resolve; and merge-grade test-to-evidence links must target stable evidence IDs.

## At merge-ready

Merge-grade quality evidence is **platform evidence, not packet opinion**. The packet identifies the exact 40-hex candidate SHA and may nominate evidence references, but it does not get to author the successful extraction result.

Each artifact-backed reference identifies a GitHub Actions workflow run, immutable artifact ID/name, and a versioned parser. The trusted verifier then:

1. resolves the workflow run from GitHub and proves it belongs to the exact candidate SHA;
2. resolves the artifact ID/name on that run and refuses missing or expired artifacts;
3. downloads the artifact through authenticated GitHub tooling;
4. computes a deterministic SHA-256 digest over the downloaded artifact files;
5. parses only a supported deterministic report format;
6. derives coverage/test facts from the report itself;
7. compares those extracted facts with the selected quality profile;
8. derives review state and reviewer identity from exact-commit GitHub review evidence;
9. checks that the live PR head and base still match the attested head/base.

The selected Work Unit quality profile cannot be lower than the repository's configured minimum. For code-changing work, line, branch, changed-line and mutation thresholds are evaluated against **extracted** evidence. Editing a packet field such as `mutation: 95` cannot turn a missing or failing platform artifact into a pass.

The verifier emits `onecompany-assurance-attestation-v1`, binding repository, Work Unit, PR, exact head, exact base, material-authorship snapshot, platform review evidence, workflow/artifact IDs, computed artifact digests, extracted quality facts, policy revision/profile and verdict. Head or base drift invalidates the attestation.

Supported first-wave artifact parsers are deliberately small and deterministic:

- `onecompany_quality_json_v1` for normalized exact-SHA quality evidence;
- `cobertura_xml` for line/branch coverage;
- `junit_xml` for family-specific test outcomes;
- `onecompany_mutation_json_v1` for normalized mutation evidence.

Unsupported formats are `UNVERIFIED`; they never degrade to a prose waiver or implicit PASS.

`python scripts/evidence_verify.py <packet.json> --repo owner/repo --pr N --base-sha <sha> --policy-revision <sha>` performs platform-backed verification. The structural `assurance` validator remains responsible for requirements/risk/traceability correctness. WU-KERNEL-003 is migrating the final merge-ready path so structural validity alone can never satisfy merge-grade assurance.

### Trust boundary

Candidate code may nominate evidence references. Candidate code may **not** be trusted to declare the extracted value, review verdict, artifact digest, or final attestation. The verifier/policy used for a merge decision must itself be rooted in a trusted base revision. WU-KERNEL-002 establishes that base-trusted referee boundary; WU-KERNEL-004 will harden platform-principal-to-CompanyOS identity/privilege mapping.

## No-code changes

Set `code_change` to false only when the candidate genuinely changes no executable code. Quantitative source-code coverage gates are then not applicable, but requirements, traceability, risk, documentation, exact-head/base provenance, review and other relevant evidence remain required.

## Waivers

A missing required assurance dimension cannot be converted to N/A informally. Use an explicit expiring waiver when policy permits it. Security/privacy/safety and critical residual-risk rules retain their human-approval boundaries. A waiver cannot manufacture absent platform evidence or change an `UNVERIFIED` artifact into verified evidence.
