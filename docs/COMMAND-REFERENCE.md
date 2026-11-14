# Command reference (supplementary)

`python onecompany.py` with no arguments lists every command. The first-run commands (`start`, `onboard`, `brief`, `journey`, `team`) are documented in [ONBOARDING](ONBOARDING.md) and the [15-minute quickstart](15-MINUTE-QUICKSTART.md). This page documents the remaining commands so each is discoverable by a fresh user. Each description is the first paragraph of the command script's own docstring; run `python onecompany.py <command> --help` (where supported) for arguments. `python onecompany.py docs-check` verifies that this page and the other documentation stay complete.

The `*-check` and `*-report` commands are deterministic and read-only on supplied inputs. Other commands (for example `init`, `attest`, `execute-dispatch`, `handoff-runtime`) can act on the repository or GitHub under their own documented guards; read the script docstring before running them.

| Command | Script | What it does |
|---|---|---|
| `python onecompany.py a11y-check` | `scripts/a11y_check.py` | Deterministic, read-only accessibility-scan check (OC-P1-04 slice 8, #449). |
| `python onecompany.py ac-coverage` | `scripts/ac_coverage.py` | Deterministic, read-only acceptance-criterion coverage report (OC-P1-04, #435). |
| `python onecompany.py assurance` | `scripts/assurance_gate.py` | Engineering assurance structure gate with optional trusted attestation. |
| `python onecompany.py attest` | `scripts/trusted_assurance.py` | Base-trusted merge-grade assurance attestation for CompanyOS. |
| `python onecompany.py comms-check` | `scripts/comms_check.py` | Deterministic, read-only agent-communication check (OC-P1-06 slice 1, #461). |
| `python onecompany.py contract-check` | `scripts/contract_check.py` | Deterministic, read-only contract/property/API/DB suite check (OC-P1-04 slice 10, #453). |
| `python onecompany.py deps-check` | `scripts/deps_check.py` | Deterministic, read-only dependency-update / staged-release check (OC-P1-09 slice 1, #463). |
| `python onecompany.py design-tokens-check` | `scripts/design_tokens_check.py` | Read-only design-token gate (OC-P1-01 slice 1). |
| `python onecompany.py evidence` | `scripts/assurance.py` | Policy-correct OneCompany engineering assurance validator. |
| `python onecompany.py execute-dispatch` | `scripts/dispatch_execute_entry.py` | A3b execute-dispatch entrypoint with reviewed automatic adapters. |
| `python onecompany.py fixture-check` | `scripts/fixture_check.py` | Deterministic, read-only running-app fixture check (OC-P1-04 slice 5, #443). |
| `python onecompany.py flaky-report` | `scripts/flaky_report.py` | Deterministic, read-only flaky-test report (OC-P1-04 slice 2, #437). |
| `python onecompany.py graph-check` | `scripts/graph_check.py` | Deterministic, read-only product-graph check (OC-P1-03 slice 1, #467). |
| `python onecompany.py handoff-runtime` | `scripts/handoff_runtime.py` | Wake OneCompany from GitHub events and reconcile authoritative state safely. |
| `python onecompany.py hardening-audit` | `scripts/hardening_audit.py` | Audit repository-wide workflow and template supply-chain invariants. |
| `python onecompany.py harness-check` | `scripts/harness_portability_check.py` | Deterministic, read-only harness portability check (OC-P1-05 slice 1, #457). |
| `python onecompany.py init` | `scripts/init_project.py` | Safely initialize a repository created from the OneCompany GitHub template. |
| `python onecompany.py knowledge-check` | `scripts/knowledge_check.py` | Deterministic, read-only knowledge store check (OC-P1-07 slice 1, #459). |
| `python onecompany.py load-check` | `scripts/load_check.py` | Deterministic, read-only load-result check (OC-P1-04 slice 7, #447). |
| `python onecompany.py mutation-check` | `scripts/mutation_check.py` | Deterministic, read-only mutation-result check (OC-P1-04 slice 6, #445). |
| `python onecompany.py outcome-report` | `scripts/outcome_report.py` | Deterministic, read-only outcome / budget report from supplied receipts (OC-P1-08, #423). |
| `python onecompany.py portfolio-check` | `scripts/portfolio_check.py` | Deterministic, read-only multi-project isolation check (OC-P1-10 slice 1, #465). |
| `python onecompany.py quarantine-check` | `scripts/quarantine_check.py` | Deterministic, read-only quarantine registry check (OC-P1-04 slice 4, #441). |
| `python onecompany.py regression-report` | `scripts/regression_report.py` | Deterministic, read-only negative-regression report (OC-P1-04 slice 3, #439). |
| `python onecompany.py release-check` | `scripts/release_check.py` | Deterministic, read-only release / incident readiness check (OC-P0-18, #421). |
| `python onecompany.py risk` | `scripts/assurance.py` | Policy-correct OneCompany engineering assurance validator. |
| `python onecompany.py schema-validate` | `scripts/schema_validate.py` | Dependency-free validation for the JSON-Schema subset used by OneCompany. |
| `python onecompany.py security-check` | `scripts/security_check.py` | Deterministic, read-only security-scan check (OC-P1-04 slice 9, #451). |
| `python onecompany.py shadow-migration` | `scripts/shadow_migration.py` | Analyze an external migration snapshot without mutating the target repository. |
| `python onecompany.py trace` | `scripts/assurance.py` | Policy-correct OneCompany engineering assurance validator. |
| `python onecompany.py verify-evidence` | `scripts/evidence_verify.py` | Platform-backed engineering evidence verification for CompanyOS assurance. |
| `python onecompany.py visual-golden-check` | `scripts/visual_golden_check.py` | Deterministic, read-only visual-golden check (OC-P1-01 slice 2, #455). |
| `python onecompany.py docs-check` | `scripts/docs_check.py` | Deterministic, read-only documentation check: required docs, relative links, command coverage (OC-P1-12 slice 1). |
| `python onecompany.py app-check` | `scripts/app_check.py` | Deterministic, read-only guided-app evidence check (OC-P1-02 slice 1, #473). |
| `python onecompany.py guided-app` | `scripts/guided_app.py` | Static no-JS guided application renderer: 8 screens, design tokens, responsive, honest empty/error/slow states, never claims completion; `--journey` and `--mission-truth` derive conservative statuses from saved read-only output (OC-P1-02 slices 2-4, #477, #479, #481). |
| `python onecompany.py certify-check` | `scripts/certify_check.py` | Deterministic, read-only end-to-end certification go/no-go: fixed scenarios, budgets, evidence, certifier independence (OC-P1-13 slice 1, #475). |
