# OneCompany GitHub App MCP adapter — sealed read-only pilot

This service starts SEALED (ONECOMPANY_ADAPTER_ENABLED defaults to false).
No merge/release/deploy/branch/PR mutation or GitHub settings tool exists.

* Endpoint: https://onecompany-github-adapter.onrender.com/mcp
* Liveness: /health/live — public, content-free
* MCP requests require Authorization: Bearer <owner-provisioned 32+ char secret>.
* App PEM resides only at /etc/secrets/github-app.pem on Render; never in Grok,
  this repository, GitHub Actions logs, MCP tool responses or API arguments.
* Installation token requests are scoped to exactly one owner-approved repo
  with contents:read and pull_requests:read, and are never returned to Grok.
* Read-only MCP tools: `onecompany_actor_identity`, `onecompany_repository_status`,
  `onecompany_pull_request_head`, `onecompany_pull_request_snapshot`,
  `onecompany_read_source`, and `onecompany_read_document`.

First-phase deployment does NOT make Grok a verified unattended writer or an
independent reviewer. See docs/GROK-GITHUB-APP-ADAPTER.md.

Security scope: `onecompany_read_document` enforces the approved live-main SHA
for Markdown; `onecompany_read_source` permits bounded allowlisted source
excerpts at **any exact 40-hex commit SHA**, including feature-branch commits.
Neither operation accepts a mutable ref. OAuth URL-encoded POST bodies are streamed under
an 8 KiB effective cap, including missing/forged Content-Length. Requirements
pin the deployed/validated Python package versions.
