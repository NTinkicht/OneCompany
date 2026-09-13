# Work Unit Assurance Packet

The assurance packet is the machine-readable contract joining requirements, acceptance criteria, risks, mitigations, design, tests and exact-head evidence for one Work Unit.

## Before implementation

The packet proves readiness: requirements are approved and objectively verifiable; acceptance criteria exist; risk has been assessed; required test families are selected from risk; architecture/documentation/release impacts are declared; traceability reaches from objective to planned verification.

Requirement statements use one `shall` obligation, avoid configured ambiguous language, carry the correct typed ID, and link to real acceptance criteria, risks, the owning Work Unit, design/architecture and planned tests. Non-functional requirements additionally carry a measurable metric, target, method and conditions.

Traceability is referentially checked rather than accepted as prose: requirement-to-test links must name real tests; requirement-to-WU links must target the packet's WU; risk-to-mitigation and mitigation-to-test links must resolve; and merge-grade test-to-evidence links must target stable evidence IDs.

## At merge-ready

Merge-grade quality evidence is **platform evidence, not packet opinion**. The packet identifies the exact 40-hex candidate SHA and nominates evidence references. It does not author the successful extraction result.

Each artifact-backed reference identifies a GitHub Actions workflow run, immutable artifact ID/name, and a versioned parser. For a merge-grade decision, `trusted_assurance` then:

1. reads the required-check policy from the reviewed **base revision**, not from candidate files;
2. proves the required referee workflow is blob-identical between the trusted base and candidate;
3. verifies the required check completed successfully on the exact candidate SHA;
4. permits quality artifacts only from that base-trusted required-check workflow run;
5. proves the workflow run is bound to the exact PR, head SHA and base SHA;
6. resolves the artifact ID/name on that run and refuses missing or expired artifacts;
7. downloads the artifact through authenticated GitHub tooling and computes a deterministic SHA-256 digest;
8. parses only a supported deterministic report format and derives coverage/test facts from the report itself;
9. loads the quality policy from the reviewed **base revision** and compares the extracted facts with that policy;
10. derives review state and reviewer identity from exact-commit GitHub review evidence;
11. checks that the live PR head and base still match the attested head/base.

The selected Work Unit quality profile cannot be lower than the base-trusted repository minimum. For code-changing work, line, branch, changed-line and mutation thresholds are evaluated against **extracted** evidence. Editing compatibility fields such as `coverage.mutation: 95`, `test_family_results.security: pass`, or `independent_review.verdict: pass` cannot turn missing or failing platform evidence into a PASS.

Legacy `coverage`, `test_family_results`, `gates`, `independent_review`, and `artifacts` packet fields may still appear during the 0.4 migration so older tooling can read packets. They are **not authoritative merge evidence**. `evidence.references` and `evidence.review_reference`, resolved by the base-trusted attestor, are authoritative.

The attestor emits `onecompany-assurance-attestation-v1`, binding repository, Work Unit, PR, exact head, exact base, material-authorship snapshot, platform review evidence, exact required check/run identity, workflow/artifact IDs, computed artifact digests, extracted quality facts, base-policy blob identities, profile, generation time and verdict. Head or base drift invalidates the attestation.

Supported first-wave artifact parsers are deliberately small and deterministic:

- `onecompany_quality_json_v1` for normalized exact-SHA quality evidence;
- `cobertura_xml` for line/branch coverage;
- `junit_xml` for family-specific test outcomes;
- `onecompany_mutation_json_v1` for normalized mutation evidence.

Unsupported formats are `UNVERIFIED`; they never degrade to a prose waiver or implicit PASS.

Use the unified CLI for the authoritative merge-grade decision:

```text
python onecompany.py assurance <packet.json> --repo owner/repo --pr N --base-sha <reviewed-base-sha>
```

For direct attestation generation/debugging:

```text
python onecompany.py attest <packet.json> --repo owner/repo --pr N --base-sha <reviewed-base-sha>
```

`python onecompany.py verify-evidence ...` is the lower-level artifact resolver/parser. It proves artifact provenance and extracted facts but does not by itself establish the base-trusted producer boundary.

### Trust boundary

Candidate code may nominate evidence references. Candidate code may **not** be trusted to declare the extracted value, review verdict, artifact digest, quality policy, required-check policy, trusted workflow, or final attestation. Those are rooted in the reviewed base revision and live GitHub platform evidence.

WU-KERNEL-002 establishes the base-trusted referee boundary. WU-KERNEL-003 consumes it for assurance. WU-KERNEL-004 will harden platform-principal-to-CompanyOS identity/privilege mapping.

### Bootstrap rule for evidence-producing workflows

A new or changed trusted referee/evidence-producing workflow cannot certify its own replacement. That would recreate the self-attestation flaw this design removes. Such a workflow change must be independently reviewed and human-promoted first; subsequent candidates may then rely on it as part of their trusted base.

The current 0.4 branch therefore intentionally fails closed if the base-trusted required-check run does not publish the referenced deterministic quality artifact. The solution is to promote an independently reviewed artifact-producing referee, **not** to accept artifacts from arbitrary candidate-added workflows.

## No-code changes

Set `code_change` to false only when the candidate genuinely changes no executable code. Quantitative source-code coverage gates are then not applicable, but requirements, traceability, risk, documentation, exact-head/base provenance, review and other relevant evidence remain required.

## Waivers

A missing required assurance dimension cannot be converted to N/A informally. Use an explicit expiring waiver when policy permits it. Security/privacy/safety and critical residual-risk rules retain their human-approval boundaries. A waiver cannot manufacture absent platform evidence or change an `UNVERIFIED` artifact into verified evidence.
