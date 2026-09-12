# Configure GitHub Copilot

Copilot has several distinct surfaces: IDE/CLI assistance, code review, cloud agent/coding work, and automations. Verify only the surfaces you actually enable.

Official references:

- https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions
- https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent
- https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/configure-secrets-and-variables

## 1. Confirm entitlement and repository availability

Confirm the account has a Copilot plan that includes the desired surface. For organization-owned repositories, organization/enterprise policy may control cloud-agent access. For user-owned repositories, confirm the repository has not opted out.

Do not equate IDE completion access with cloud-agent/review readiness.

## 2. Repository instructions

OneCompany includes:

```text
AGENTS.md
.github/copilot-instructions.md
```

GitHub documents `AGENTS.md` as shared agent context and `.github/copilot-instructions.md` as repository-wide Copilot guidance. Keep them non-conflicting.

For code review, verify repository custom instructions are enabled under **Settings → Copilot → Code review**.

## 3. Cloud agent / coding agent

If desired, enable repository access to Copilot cloud agent in the relevant personal/org policy. GitHub cloud agent works on one repository/branch per session and creates a bounded PR-oriented stream, which fits OneCompany well — but it must still consume the existing canonical stream when taking over a WU rather than creating a competing implementation.

If the agent needs private package credentials or other resources, use GitHub's **Secrets and variables → Agents** store, not source files. Grant the minimum scope.

## 4. Code review

Start with manual review requests. Verify Copilot can review the current PR and that repository instructions are applied.

For OneCompany exact-head gating, every material push after a review makes the previous gate stale. If you later enable automatic review/rulesets, ensure the configuration reviews new pushes or explicitly re-request review.

Copilot coding-agent authorship and Copilot code review are treated as the **same actor** for self-gating. A Copilot-authored candidate needs another independent actor for the final gate.

## 5. Cost/capacity

Copilot agentic features and reviews may consume plan-specific premium requests/credits and, in private repositories, GitHub Actions/runner capacity depending on the feature. A zero-extra-spend OneCompany should disable/avoid overage and verify the relevant entitlement before enabling unattended automations.

## 6. Development environment

If the cloud agent needs deterministic setup beyond auto-detection, use a reviewed setup workflow. OneCompany ships `.onecompany/templates/workflows/copilot-setup-steps.yml.disabled` as a starting point. Keep setup steps deterministic, bounded, and free of broad secrets.

## Smoke checklist

- [ ] Copilot entitlement confirmed for each desired surface.
- [ ] Repository is permitted for cloud agent if used.
- [ ] `AGENTS.md` and `.github/copilot-instructions.md` are present and non-conflicting.
- [ ] Coding smoke passed before `implementation` is verified.
- [ ] Code review smoke passed on a non-authored exact head.
- [ ] Same-actor rule for coding agent/code review is understood.
- [ ] Agent secrets, if any, use GitHub Agents secret store and least privilege.
- [ ] Overage/Actions-cost behavior is compatible with `.onecompany/budget.json`.
