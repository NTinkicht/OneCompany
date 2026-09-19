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
* Six read-only MCP tools: onecompany_actor_identity,
  onecompany_repository_status, onecompany_read_document,
  onecompany_pull_request_head, onecompany_pull_request_snapshot, and
  onecompany_read_source. The PR snapshot uses a fixed base/head SHA comparison
  and rejects races; source reads require a 40-hex commit SHA and bound paths
  and line counts. Only onecompany_read_document requires the LIVE main SHA.

First-phase deployment does NOT make Grok a verified unattended writer or an
independent reviewer. See docs/GROK-GITHUB-APP-ADAPTER.md.

Security scope: Markdown reads through onecompany_read_document are pinned
to the live main SHA. Bounded code excerpts may also come from feature-branch
commits at an immutable 40-hex SHA; bounded PR metadata and changed-file
paths are available for open PRs in the approved OneCompany repository.
No feature-branch write or independent review attestation is exposed.
OAuth URL-encoded POST bodies are streamed under an 8 KiB effective cap,
including missing/forged Content-Length. Requirements pin the
deployed/validated Python package versions.
