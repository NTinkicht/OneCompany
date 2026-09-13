# Security

The detailed model is in [`docs/SECURITY.md`](docs/SECURITY.md).

## Reporting a vulnerability

Do not publish credentials, exploit details affecting a live deployment, private repository content, or sensitive user data in a public issue. Use the repository owner's private/security reporting channel when available.

## High-risk areas

Security review is especially important for changes involving:

- GitHub Actions permissions and `pull_request_target`;
- secrets/tokens/provider credentials;
- unattended write or merge authority;
- budget/billing automation;
- policy parsing and prompt-injection boundaries;
- production deployments/destructive operations;
- external agent/plugin/tool execution;
- logging or persistence of user/regulated data.

## Default stance

Least privilege, exact-head verification, non-author review, no secret-bearing prompts/logs, and human approval for credential/budget expansion.
