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
`wu-grok-001-github-app-mcp-adapter` **only for pre-merge qualification**,
automatic deploy **off**. After governed merge to main, switch the persistent
Render service source branch to `main` while keeping automatic deploy off;
deploy the verified main commit and confirm read-only App identity again.

- Build: `pip install -r services/github_app_adapter/requirements.txt`
- Start: `PYTHONPATH=services/github_app_adapter uvicorn server:app --host 0.0.0.0 --port $PORT`
- Liveness: `https://onecompany-github-adapter.onrender.com/health/live`
- MCP: `https://onecompany-github-adapter.onrender.com/mcp`
- `ONECOMPANY_ADAPTER_ENABLED=false` until real App/connector tests are ready; this initial qualification is complete and the installed service currently has it enabled.
- `ONECOMPANY_PUBLIC_HOST=onecompany-github-adapter.onrender.com`

A `/health/live` response does not prove that GitHub authentication or
MCP identity is configured. Render Free may sleep when idle; this pilot is
not a qualified always-on unattended worker.

## Owner-only GitHub App setup

Owner explicitly chose to skip a separate disposable repository and use
**NTinkicht/OneCompany directly** for this first identity check. Register/install
the GitHub App with **Metadata:read**, **Contents:read**, and **Pull requests:read**
on that repository; do not enable write permissions yet. If the adapter reports
`github_repository_installation_lookup_github_http_status_404`, open
GitHub > Settings > Developer settings > GitHub Apps > edit
**OneCompany Grok Worker** > Install App > install/configure the
`NTinkicht` account > Only select repositories > `OneCompany` > Save.
No new PEM, Grok OAuth login, App ID or installation ID is needed. The adapter's own
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
| `GITHUB_APP_INSTALLATION_ID` | Optional legacy setting; ignored in favor of the App installation detected on the approved repository |
| `GITHUB_APP_PRIVATE_KEY_FILE` | `/etc/secrets/github-app.pem` (default) |
| `ONECOMPANY_APPROVED_REPOSITORY` | Exactly NTinkicht/OneCompany for the owner-approved read-only identity check |
| `ONECOMPANY_CONNECTOR_BEARER` | A random secret of 32+ characters, owner-generated and kept in Render and Grok's authentication UI |
| `ONECOMPANY_ADAPTER_ENABLED` | `true` only after every required setting is installed and checked |

For App ID 5003121, OneCompany is the allowlisted repository. The adapter
**discovers the repository installation ID directly from GitHub**, so any old
value in GITHUB_APP_INSTALLATION_ID is ignored. It does not permit choosing
another installation through connector input. Do not record the private key
or connector bearer in GitHub.

The bearer authenticates *to the MCP adapter*, not to GitHub. The App PEM
never leaves Render; short-lived installation tokens are limited to the
single approved repository and read-only permissions.

## Connect Grok

Grok's **web custom connector requires OAuth**, not static bearer entry. The
same Render service now implements a single-owner, read-only OAuth + PKCE
bridge, authenticated with the already-configured Render connector bearer
through an owner-only browser consent form. Do NOT paste the GitHub App PEM
or OAuth access tokens into a model conversation. Grok receives OAuth access
and refresh tokens, never the Render secret or GitHub installation token.

Use Grok > Connectors > New Connector > Custom, MCP URL
`https://onecompany-github-adapter.onrender.com/mcp` and:

| Grok field | Exact value |
|---|---|
| Client ID | `onecompany-grok-web` |
| Client Secret | **Leave empty** (public client with PKCE) |
| Authorization Endpoint | `https://onecompany-github-adapter.onrender.com/oauth/authorize` |
| Token Endpoint | `https://onecompany-github-adapter.onrender.com/oauth/token` |
| Scopes | `onecompany:read` |
| Token Auth Method | `none (PKCE only)` |

When redirected to the OneCompany-branded authorization page, enter the
**existing** `ONECOMPANY_CONNECTOR_BEARER` value privately into its password
field once. This is the secret used to authorize a browser session; do not
paste it into the Grok chat, client ID/secret field or URL. The OAuth bridge
accepts only allowlisted Grok callback URLs, binds exchanges to PKCE S256,
consumes authorization codes once, and issues audience-bound one-hour access
and renewable 30-day refresh credentials. Rotating the Render connector
secret invalidates all sessions.

If Grok rejects a blank Client Secret or the callback URL differs from the
allowlist, STOP and report the field/error without sending credentials; do
not weaken authentication or guess alternative OAuth endpoints.

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

## Actual actor qualification (2026-09-19)

Grok's web connector completed both `onecompany_actor_identity` and
`onecompany_repository_status`. The reported actor was
`grok-4-6-interactive`, GitHub principal `onecompany-grok-worker[bot]`,
App ID `5003121`, dynamically discovered installation ID `163077002`,
repository `NTinkicht/OneCompany`, and `read_only` mode. Render deployment
`dep-dane5fmk1f9s738e5tig` independently logged
`verified_read_only_identity`. Grok is enabled for *read-only interactive
repository intelligence* with **zero implementation capacity**. This is not
an unattended worker or independently authenticated final reviewer.

The GitHub App is also installed on Tabibi and Veritas-Atlas, but this adapter
accepts **only NTinkicht/OneCompany**. Further repository scope requires a
separate explicit authorization and Work Unit; no cross-repo capability is
inferred from installation-level permissions.

## Read-document scope and reviewed runtime hardening

`onecompany_read_document` accepts only allowlisted README/AGENTS/docs Markdown
at the **current main commit SHA**, independently resolved by the server
immediately before the GitHub contents request. It rejects historical or
feature-branch SHA reads. This phase does not grant project-wide source or
candidate-PR file access. Future PR/source inspection is a distinct,
separately reviewed Work Unit (#105 / PR #106).

The OAuth POST handler enforces an 8 KiB cap on the **actual streamed bytes**
before decoding the bounded URL-encoded form, including chunked/no-Length
requests. CI and Render install the same exactly pinned dependency versions
from `services/github_app_adapter/requirements.txt`; upgrades require a new
reviewed commit and exact-head validation. This preserves the existing public
OAuth callback and unchanged connector credentials.

## PR snapshot and write qualification boundary (2026-09-20)

The read-only PR snapshot fetches the current PR before and **again after**
GitHub's moving `/pulls/{number}/files` response, failing closed if its head,
base or relevant identity changes. Rename entries preserve `previous_path`.
Deleted/foreign fork repositories are sanitized refusals, not traceback data.
The adapter never treats this read-only snapshot as independent final review.

Grok can inspect OneCompany under `onecompany-grok-worker[bot]`, but full
interactive bot-written WU contributions remain **unqualified**. The merged
internal writer is not an MCP write tool; it is sealed by default and still
requires exact native WU lease authority, OAuth write-scope separation,
owner-approved GitHub App permissions and a live bot-authored smoke test.
See Issue #105. Do not expand App permissions to Tabibi or Veritas-Atlas to
qualify the OneCompany-only adapter. The source autonomy level is still L1.
