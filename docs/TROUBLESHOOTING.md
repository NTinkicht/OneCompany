# Troubleshooting

Diagnose from evidence before changing configuration. Do not widen permissions, disable tests, or enable paid fallback as a first response.

## Actor appears configured but router rejects it

Run:

```bash
python onecompany.py readiness --actor <id> --local-probe
python onecompany.py route --capability <capability>
```

Common causes:

- actor `enabled=false`;
- `configured=false`;
- setup state is not `ready`/`degraded`;
- capability is declared but not verified;
- capability is temporarily unavailable;
- repository read/write/review/merge access is not verified;
- budget rejects the cost class;
- reviewer is a material author.

The rejection list is intentional: fix the specific missing condition rather than bypassing routing.

## Review quota exhausted but coding still works

Do not mark the entire actor unavailable. Add only `code_review` to `temporarily_unavailable_capabilities`; preserve `implementation` if it remains proven/available. Route review elsewhere.

## Agent says it is working but nothing moves

Check durable evidence: branch/head, PR updates, CI, review artifact, issue transition. Assignment or heartbeat alone is not progress. Reconcile before failover; do not wake a second implementer blindly.

## CI mechanical failure repeats

Use the repository-pinned formatter/linter/codegen tool in an executable environment. Do not manually approximate canonical tool output. Keep remediation on the existing stream.

## Review says PASS but PR head changed

The gate is stale. Re-run the required exact-head review/CI on the new SHA. Do not merge based on an old comment.

## GitHub connected but agent cannot push

Read access and write access are separate. Check the exact product surface, GitHub app/PAT permission, branch/ruleset restrictions, and execution environment Git credential. Test on a disposable branch.

## `gh` works locally but cloud agent cannot access repository

The cloud/runtime has its own credential context. Configure that environment explicitly; never copy your personal token into repository files.

## Gemini/Mistral key works but budget policy rejects actor

Correct behavior. Credential validity does not establish cost eligibility. Verify free/subscription/PAYG settings and change budget/readiness only with authorized evidence.

## Unattended workflow prints sensitive material

Disable the workflow first. Revoke/rotate potentially exposed credentials. Inspect Actions logs/artifacts/comments, then fix redaction/tool boundaries before re-enabling. Do not continue running it for debugging.

## Branch protection blocks a cloud coding agent

Do not globally weaken protection immediately. Check whether the platform requires an explicit app/bypass actor or a different allowed branch workflow. Preserve required CI/review/expected-head invariants.

## `STATE.json` disagrees with GitHub

GitHub/live repository evidence wins. Run reconciliation and fix the cache. Never merge/fail over because the cache says something historical.

## No independent reviewer remains

Stop at review-ready state. Do not manufacture independence by changing prompts/personas/accounts for the same material actor. Use another eligible actor or a human review.

## No allowed capacity remains

Surface `CAPACITY_DEGRADED/BLOCKED`, preserve the stream, and wait/fail over within already-authorized capacity. A quota problem is not financial authorization.
