# Configure Claude / Claude Code

Claude can be used interactively through Claude Code and, optionally, through a GitHub Action. Treat those as execution surfaces of the same actor for material-authorship/self-gating purposes.

Official documentation changes over time; start from Anthropic's Claude Code GitHub Actions documentation and verify current setup before enabling automation.

## 1. Interactive Claude Code

Install/sign in to Claude Code using Anthropic's current instructions, open the repository, and verify:

```bash
claude --version
git status
```

Have Claude read `AGENTS.md`, inspect a known source file, and identify the current branch without editing. Then grant a disposable implementation WU if you want to verify write capability.

## 2. Optional GitHub Action

Anthropic's supported setup can install/configure the GitHub app from Claude Code. A common interactive setup path is `/install-github-app`.

For subscription-backed Claude Code environments, Anthropic supports generating an OAuth credential with `claude setup-token` for compatible GitHub Action setups. Store the result only as a GitHub Actions secret such as `CLAUDE_CODE_OAUTH_TOKEN` when the current official action supports that route.

An Anthropic API key is a **separate metered billing path**. Do not substitute it merely because an Action needs authentication unless the OneCompany budget explicitly authorizes API spend.

OneCompany ships a disabled reference workflow in `.onecompany/templates/workflows/claude.yml.disabled`. Review current Anthropic action documentation and pin/review the action revision before enabling it in `.github/workflows/`.

## 3. Permissions

Start with the smallest permissions the job requires. Read-only review needs less than implementation. If Claude must inspect Actions/CI, add `actions: read`; do not grant admin/secrets/environment write.

Any issue/PR mention trigger is untrusted input. The repository policy and Work Unit remain higher authority than comment text.

## 4. Smoke tests

- Read: inspect `AGENTS.md` and current exact PR head.
- Review: on a non-authored test PR, produce a verdict naming the exact SHA.
- Write: if leased, modify a disposable branch and run tests.
- Action: invoke the disabled-template equivalent on a setup issue/PR and confirm permissions/logging before production use.

## 5. Independence

If interactive Claude or the Claude Action materially changes the candidate head, actor=`claude` is a material author and cannot serve as the sole independent final gate for that head. Switching Claude surfaces does not manufacture independence.

## Smoke checklist

- [ ] Claude Code installed/authenticated if interactive use is desired.
- [ ] Repository read smoke passed.
- [ ] Write smoke passed before `implementation` is marked verified.
- [ ] Optional GitHub Action tested with least privilege.
- [ ] Subscription OAuth and metered API paths are not confused.
- [ ] Exact-SHA review path tested on non-authored work.
