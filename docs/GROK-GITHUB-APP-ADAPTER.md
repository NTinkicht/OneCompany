# WU-GROK-001 — GitHub App identity and Render MCP pilot

Independent GitHub issue #103 and PR #104. The existing A4 factory PR #102
remains its own canonical WU and is not altered by this integration.

**Phase 1 is a sealed, read-only identity pilot.** It does not create PRs,
commit code, review as an independent attestor, merge, release, deploy customer
code, grant credentials or raise OneCompany's source L1 autonomy.

## Render service

Create a service named `onecompany-github-adapter` in NTinkicht's existing
Render workspace with Free plan, Frankfurt, Python runtime, source
`NTinkicht/OneCompany`, branch
`wu-grok-001-github-app-mcp-adapter`, automatic deploy **off**.

- Build: `pip install -r services/github_app_adapter/requirements.txt`
- Start: `PYTHONPATH=services/github_app_adapter uvicorn server:app --host 0.0.0.0 --port $PORT`
- Liveness: `https://onecompany-github-adapter.onrender.com/health/live`
- MCP: `https://onecompany-github-adapter.onrender.com/mcp`
- `ONECOMPANY_ADAPTER_ENABLED=false` until real App/connector tests are ready.
- `ONECOMPANY_PUBLIC_HOST=onecompany-github-adapter.onrender.com`

A `/health/live` response does not prove that GitHub authentication or
MCP identity is configured. Render Free may sleep when idle; this pilot is
not a qualified always-on unattended worker.

## Owner-only GitHub App setup

Owner explicitly chose to skip a separate disposable repository and use
**NTinkicht/OneCompany directly** for this first identity check. Register/install
the GitHub App with **Metadata:read**, **Contents:read**, and **Pull requests:read**
on that repository; do not enable write permissions yet. The adapter's own
GitHub installation token request also explicitly downscopes these permissions
to read-only and one repository, regardless of any broader App installation
permissions. This is **not** a substitute for the two distinct live A4 pilots
required by issues #90/#92. In Render > service > Environment > Secret Files, add
`github-app.pem` with the complete downloaded private key. Render mounts
it at `/etc/secrets/github-app.pem`. Never send that PEM to Grok, this chat,
GitHub, a PR, or a model-accessible tool response.

Set the following variables in Render, not in the source code:

| Key | Value |
|---|---|
| `GITHUB_APP_ID` | Numeric non-secret App ID |
| `GITHUB_APP_INSTALLATION_ID` | Numeric non-secret Installation ID |
| `GITHUB_APP_PRIVATE_KEY_FILE` | `/etc/secrets/github-app.pem` (default) |
| `ONECOMPANY_APPROVED_REPOSITORY` | Exactly NTinkicht/OneCompany for the owner-approved read-only identity check |
| `ONECOMPANY_CONNECTOR_BEARER` | A random secret of 32+ characters, owner-generated and kept in Render and Grok's authentication UI |
| `ONECOMPANY_ADAPTER_ENABLED` | `true` only after every required setting is installed and checked |

For App ID 5003121 and installation ID 163051959, OneCompany is the
allowlisted repository. These identifiers are non-secret; do not record the
private key or connector bearer in GitHub.

The bearer authenticates *to the MCP adapter*, not to GitHub. The App PEM
never leaves Render; short-lived installation tokens are limited to the
single approved repository and read-only permissions.

## Connect Grok

Use Grok > Connectors > New Connector > Custom with the public `/mcp`
URL and the supported authentication UI. **Verify that the actual Grok UI
supports the required bearer configuration before enabling the service.**
If it does not, stop; do not put credentials in the URL or disable auth.
A separately reviewed OAuth integration can be built subsequently.

Invoke `onecompany_actor_identity`. It should identify logical actor
`grok-4-6-interactive` separately from the GitHub App principal
`<app-slug>[bot]`, confirm the approved repository NTinkicht/OneCompany, and state that
writing and independent review remain disabled. The GitHub connector
running under `NTinkicht` is a *different* execution identity and must
not be treated as evidence of the App principal.

## Gates before enabling writes

Only a subsequent reviewed Work Unit may add narrowly scoped commit/PR
tools. It must enforce a verified durable WU lease, canonical branch/PR,
exact-head/base SHA, permitted file paths, cumulative material authors,
trusted default-branch policy, emergency stop, budget, and server-side
protection. The GitHub App's permissions themselves cannot express
'contents write but no merge' under a bypassable GitHub branch policy.
A writer App is not the same identity as an independent review-attestation App.

**Never record Grok as unattended or independently review-capable merely
because an interactive connector works.**
