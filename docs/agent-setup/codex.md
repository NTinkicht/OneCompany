# Configure Codex

Codex is a strong default implementation/CI-remediation runtime when its connected environment has repository write access. Configuration is surface-dependent, so OneCompany verifies the exact execution path rather than assuming that a ChatGPT/Codex subscription implies Git access.

## 1. Prefer the native repository connection

If your Codex surface can already open the intended GitHub repository, create branches, push commits, and interact with PRs, use that native path. Grant only the repositories and permissions required.

## 2. Optional cloud-workspace GitHub authentication fallback

When a Codex cloud workspace has the repository checkout but no usable Git credential, OneCompany includes a reference pattern under `.onecompany/templates/scripts/codex-cloud-github-auth.sh.template`, derived from a reviewed cloud-workspace authentication pattern.

Use a **fine-grained GitHub PAT restricted to the target repository and minimum permissions**. Store it only in the Codex environment's secret store. Never commit it and do not put it in `.onecompany/*.json`.

The helper pattern authenticates `gh` from stdin, runs `gh auth setup-git`, verifies `gh auth status`, and verifies the remote with `git ls-remote` without printing the token.

Prefer GitHub App/native auth over PATs when it provides the required capability.

## 3. Smoke-test capabilities independently

Read test:

```bash
git status
git remote -v
git ls-remote --exit-code origin HEAD
```

Write test: use a disposable setup WU/branch, make a harmless documentation change, push it, and create/update the intended PR. Do not test by pushing directly to protected `main`.

CI-remediation test: reproduce a deterministic test/formatter failure in the executable environment and run the repository-pinned tool rather than guessing output.

Review test: review a head Codex did not materially author. Review capacity may have a different quota from implementation capacity.

Merge test: only after policy permits, verify the executor can merge **with expected-head protection**. A generic ability to push is not merge readiness.

## 4. Record readiness per capability

A useful record after setup might include:

```text
verified_surfaces: codex_cloud
verified_capabilities: implementation, repository_intelligence, ci_remediation, test_design
repository_access: read=true, write=true
```

Add `code_review` and `merge_execution` only after those paths are independently verified.

If review quota is exhausted, put `code_review` in `temporarily_unavailable_capabilities` while leaving working implementation capability routable.

## 5. Failover behavior

When Codex takes over an existing WU, continue the existing branch/PR and inherit scope, tests, findings, and material-author history. A recovered preferred actor does not preempt healthy replacement work mid-attempt.

## Smoke checklist

- [ ] Exact repository readable.
- [ ] Write tested on non-default branch.
- [ ] CI commands run in the actual execution environment.
- [ ] Review tested separately from implementation.
- [ ] Merge tested only if role requires it.
- [ ] Fine-grained credential, if needed, lives only in the execution environment secret store.
- [ ] Capability-specific quota state is represented separately.
