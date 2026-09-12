# GitHub Setup

## Repository settings

Recommended starting posture:

- protected `main`/default branch;
- pull requests required for material changes;
- required CI checks for deterministic quality;
- disallow force pushes/deletions on protected branch;
- merge method standardized (squash is often simplest for WUs, but project choice);
- auto-merge disabled until L3 maturity is proven;
- Actions permissions kept minimal.

## GitHub App / token permissions

Grant workers only what their role needs.

### Read-only scout

```text
metadata: read
contents: read
issues: read
pull requests: read
checks/actions: read
```

### Implementer

Add only the write scopes needed for branch contents, issues/PR comments, and workflow triggering. Avoid admin/secrets/environment write unless essential.

### Merge executor

Needs PR merge ability but should not automatically gain repository administration.

## Actions

`onecompany-validate.yml` uses read-only contents permission and no secrets.

The scheduled watchdog is shipped as `.disabled` because private repositories may incur Actions usage and because unattended issue/write behavior should be explicitly reviewed before activation.

## Labels

Recommended labels:

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

OneCompany does not require labels to be the source of truth; they are useful query/index signals.

## Branch naming

Recommended:

```text
wuNN-short-description
infra-short-description
governance-short-description
incident-short-description
```

Failover keeps the existing branch.

## Merge protection

When using an API/connector, pass the expected approved head SHA if supported. If the API reports the head moved, do not retry blindly: reconcile and re-gate.
