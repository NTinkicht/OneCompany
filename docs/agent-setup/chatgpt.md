# Configure ChatGPT

This guide separates **ChatGPT repository reading** from **repository mutation**. Do not mark write capabilities ready just because GitHub is connected to ChatGPT.

Official reference: https://help.openai.com/en/articles/11145903-connecting-github-to-chatgpt-drease

## 1. Connect GitHub for repository context

In ChatGPT, open **Settings → Apps/Plugins** (wording can vary by surface), select GitHub, install/authorize the ChatGPT GitHub app, and choose the repositories it may access.

For organization repositories, an administrator may need to approve the app. For private/new repositories, verify the GitHub app is installed for the correct account and the repository is selected.

The standard GitHub connection provides live repository retrieval for supported ChatGPT workflows. Treat this as **read capability unless the exact surface you are using exposes a separate authorized write action**.

## 2. Verify read access

Use a harmless repository question:

```text
Read AGENTS.md and tell me the configured source of truth and current autonomy level.
```

Then ask it to identify a known file and current PR/head using connected GitHub tooling when available.

Record in `.onecompany/readiness.json` only after evidence exists:

```text
setup_state: partially_ready or ready
verified_surfaces: [chatgpt_github]
verified_capabilities: architecture, planning, repository_intelligence, documentation, research, state_reconciliation
repository_access.read: true
```

## 3. Configure write execution separately

For direct implementation, prefer an explicitly write-capable surface such as Codex or another connected repository action. ChatGPT subscription access does **not** imply OpenAI API billing and does not itself prove repository write permission.

If your ChatGPT surface has an authorized GitHub write action, test it on a disposable setup Work Unit/branch before setting `repository_access.write=true` or verifying `implementation`/`ci_remediation`.

## 4. Review and merge

Only mark `code_review` verified after ChatGPT can inspect the exact PR head and publish a durable review artifact. Only mark merge access after an expected-head-protected merge path has been tested. A ChatGPT-authored head remains conflicted from sole independent final review.

## 5. Budget rule

A ChatGPT Plus/Pro/Business subscription and an OpenAI API account are different cost surfaces. Do not introduce API keys, API billing, credits, or automatic paid fallback unless `.onecompany/budget.json` explicitly permits them.

## Smoke checklist

- [ ] GitHub app connected to the intended account/repository.
- [ ] `AGENTS.md` can be read from live repository evidence.
- [ ] Current PR/head can be reconciled when the product surface supports it.
- [ ] Write capability, if any, was tested separately.
- [ ] Review capability, if used, was tested on a non-authored head.
- [ ] No API-billing assumption was introduced.
