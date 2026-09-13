# Configure Mistral Vibe

Vibe is useful for failure analysis, adversarial test design, repository reasoning, and bounded implementation. Its account/API-key path can map to free, subscription, or PAYG usage, so cost state must be explicit.

Official references:

- https://docs.mistral.ai/vibe/code/cli/install-setup
- https://docs.mistral.ai/vibe/code/cli/configuration-reference

## 1. Install

Mistral documents a one-line installer on macOS/Linux:

```bash
curl -LsSf https://mistral.ai/vibe/install.sh | bash
```

Manual installation supports Python 3.12+ with `uv tool install mistral-vibe` or `pip install mistral-vibe`.

Verify:

```bash
vibe --version
```

For unattended/company-critical use, pin a tested version rather than depending on automatic upgrades.

## 2. Sign in / configure

Run:

```bash
vibe
```

The first launch runs setup; `vibe --setup` can rerun it. Vibe can sign in with a Mistral account or use a compatible API key. Configuration normally lives under `~/.vibe/`; `VIBE_HOME` can isolate state.

A Mistral key can be usable under free, plan, or PAYG settings. **Key validity is not proof of zero-spend eligibility.** Verify PAYG/overage policy separately.

## 3. Interactive read smoke

From the repository, ask Vibe to read `AGENTS.md` and identify a bounded set of files relevant to a harmless question. Then confirm:

```bash
git status --short
```

Mark read/scout/failure-analysis/test-design capability ready only after evidence.

## 4. Tool permissions

Vibe supports `enabled_tools` / `disabled_tools` and per-tool permission configuration. Programmatic operation can be more permissive than an interactive approval flow, so **tool allow-lists are an authority boundary**.

For an unattended read-only scout, expose only the minimum read/search tools. Do not expose shell/write/MCP merely for convenience.

## 5. Unattended mode

OneCompany ships `.onecompany/templates/workflows/mistral-vibe-wake.yml.disabled`.

Before enabling it:

- confirm the plan/PAYG state;
- configure a trusted/owner-only trigger;
- pin `ONECOMPANY_MISTRAL_VIBE_VERSION`;
- set `ONECOMPANY_MISTRAL_PAYG_DISABLED_CONFIRMED=true` only after checking account settings;
- store `MISTRAL_API_KEY` in GitHub Actions secrets only if that unattended path is explicitly authorized;
- isolate `VIBE_HOME`;
- disable auto-update/notifications/telemetry where deterministic CI operation requires it;
- allow only read/search tools for the generic wake;
- set max turns/tokens and a hard timeout;
- classify failures without printing provider response bodies;
- redact key/bearer patterns before publishing output.

## 6. Write/review

A write-capable Vibe session requires an implementation lease and a verified Git path. If Vibe materially authors the head, it cannot be the sole independent reviewer. Generic unattended scouting is non-gating by default.

## Smoke checklist

- [ ] Supported installation completed and `vibe --version` works.
- [ ] Account/API-key path configured.
- [ ] PAYG/overage state explicitly checked.
- [ ] Read-only repository smoke passed.
- [ ] Tool allow-list tested before unattended use.
- [ ] Write capability tested separately if needed.
- [ ] Unattended timeout/redaction/cost guards are in place if enabled.
