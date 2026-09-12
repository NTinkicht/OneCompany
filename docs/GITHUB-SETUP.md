# GitHub Setup

GitHub is OneCompany's operational source of truth, so repository controls are part of the company security model.

## Recommended starting posture

- protect `main`/default branch with a ruleset or branch protection;
- require pull requests for material changes;
- require deterministic project CI checks;
- disallow force pushes/deletions on the protected branch;
- standardize merge method where practical;
- keep auto-merge disabled until L3 maturity is proven;
- keep default Actions `GITHUB_TOKEN` permissions read-only where practical and elevate per workflow;
- treat changes to agent/workflow/governance files as security-sensitive.

Run the advisory read-only audit when `gh` has access:

```bash
python onecompany.py audit-github
```

A warning can mean the token lacks admin visibility rather than the control is absent; verify in GitHub Settings.

## Required checks

OneCompany's own `OneCompany Validate` check protects the control plane. Your product still needs its own deterministic checks: format/lint/type/tests/integration/migrations/build/security as appropriate.

Protect the checks that actually define your product's merge contract.

## Credential families are different

Do not treat these as interchangeable:

- GitHub App installation token/authorization;
- `GITHUB_TOKEN` inside Actions;
- fine-grained PAT in an external agent workspace;
- Copilot **Agents** secrets/variables;
- provider OAuth/API credentials.

A credential should exist only in the surface that needs it and with minimum repository scope.

## Permission profiles

### Read-only scout

```text
metadata: read
contents: read
issues/pull requests: read
checks/actions: read when needed
```

### Implementer

Add only the write scopes needed for the canonical branch plus issue/PR coordination. Avoid repository administration, secrets, environments, rulesets, or organization permissions.

### Reviewer

Needs exact-head read plus a durable way to publish review/findings. It does not need implementation write permission merely to review.

### Merge executor

Needs the narrow merge capability. Merge authority does not imply admin/secrets/workflow modification authority.

## Copilot cloud agent

Copilot cloud agent access is controlled by account/org policy and repository access. If it needs external/private resources, GitHub exposes **Settings → Secrets and variables → Agents**. Keep those secrets scoped to selected repositories/resources.

A repository may use `.github/workflows/copilot-setup-steps.yml`; GitHub requires the single job to be named `copilot-setup-steps`. OneCompany provides a disabled template. Review any setup workflow because it can influence the agent execution environment.

Copilot agentic work/code review can consume plan-specific premium usage and private-repository Actions capacity; include this in the budget decision before unattended automation.

## Actions

`onecompany-validate.yml` uses read-only contents and no provider secrets.

The scheduled watchdog is shipped `.disabled` because private-repository runner cost and unattended write/notification behavior require explicit review.

Provider wake examples live under `.onecompany/templates/workflows/*.disabled`; bootstrap does not activate them.

## Labels

Recommended optional labels:

```text
work-unit
blocker
human-decision
incident
governance
security
capacity
budget
review-required
merge-ready
```

Labels are query/index signals, not the sole source of lease/gate truth.

## Branch naming

```text
wuNN-short-description
infra-short-description
governance-short-description
incident-short-description
```

Failover keeps the existing branch.

## Expected-head merge

When using an API/connector, pass the approved head SHA if supported. If the head moved, do not retry blindly: reconcile CI/authorship/review and obtain a new exact-head gate.

## Untrusted PRs/forks

Do not expose write tokens or secrets to arbitrary fork code. Be especially careful with `pull_request_target` and with workflows that check out untrusted PR content while holding privileged tokens.

## CODEOWNERS / governance controls

For teams, consider requiring human/security ownership for changes to `.github/workflows/`, `.onecompany/`, `AGENTS.md`, security policy, deployment/IaC, and credential configuration. This is optional but useful when more humans can modify governance.
