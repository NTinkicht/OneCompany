# Configure Gemini CLI

Gemini CLI is especially useful as a repository-intelligence/regression-scout lane. Start read-only and prove the runtime before putting it on a critical path.

Official references:

- https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/installation.mdx
- https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/authentication.mdx

## 1. Prerequisite and install

Gemini CLI currently requires Node.js 20+.

```bash
node --version
npm install -g @google/gemini-cli
gemini --version
```

Google also documents Homebrew and other installation paths. For governed automation, pin an exact tested version rather than floating on `latest`.

## 2. Choose authentication intentionally

For individual/local use, Google's recommended path is normally **Sign in with Google** from `gemini`. This can use a free/Code Assist allowance depending on the account.

A `GEMINI_API_KEY` is a different authentication/cost path. Vertex AI is another distinct path and normally implies Google Cloud configuration/billing. A zero-extra-spend company must verify the chosen account/key remains in an allowed cost class before routing work.

Do not infer “free” from the existence of an API key.

## 3. Interactive read smoke

Start in the repository:

```bash
gemini
```

Ask Gemini to read `AGENTS.md`, list the current Work Unit state, and produce a bounded impact map without editing. Confirm no unexpected repository changes:

```bash
git status --short
```

Only then mark repository-intelligence/research/scouting capabilities verified.

## 4. Write smoke only when explicitly desired

Implementation requires a real implementation lease plus a separate independent reviewer. Test on a disposable branch/WU and verify Git credentials, tests, and push behavior. Read-only scouting does not need write permission.

## 5. Unattended mode

Headless use can require an API-key or other supported headless authentication path. OneCompany therefore ships unattended automation **disabled by default** at `.onecompany/templates/workflows/gemini-cli-wake.yml.disabled`.

Before enabling it:

- explicitly confirm the credential/cost path is allowed;
- set an owner-only or otherwise trusted trigger;
- pin `ONECOMPANY_GEMINI_CLI_VERSION`;
- set `ONECOMPANY_GEMINI_ZERO_BILLING_CONFIRMED=true` only after verifying billing state;
- store `GEMINI_API_KEY` only in GitHub Actions secrets if that key path is explicitly authorized;
- use a deny-all/read-only tool policy for scouting;
- apply a hard timeout;
- redact model/tool output before publishing;
- keep the generic unattended lane non-gating unless a separate exact-head review dispatch satisfies all review rules.

Do not rely on an experimental/plan mode alone as a security boundary. Tool permissions/policy should enforce read-only authority.

## Smoke checklist

- [ ] Node 20+.
- [ ] Pinned/tested Gemini CLI installed.
- [ ] Auth method and its cost class explicitly understood.
- [ ] Interactive read smoke leaves repository clean.
- [ ] Implementation tested separately before write capability is verified.
- [ ] Unattended path, if used, has explicit cost guard, tool allow-list, timeout, and redaction.
- [ ] Vertex/paid API fallback is not silently enabled.
