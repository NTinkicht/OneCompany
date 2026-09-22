# Grok Bot: provider-cloud reviewer and tester inbox

This is source-only integration code for the EXISTING OneCompany Engineer Bot.
Native scheduled read-only Grok is independently observed in issue #131.
This bridge will require an authenticated GitHub actor belonging to the Bot
and will not confuse an owner's OAuth comment with Bot execution.

## One-time owner action: extend the current routine

Edit onecompany-cloud-intake-smoke; do not create competing agents. On a
ONECOMPANY-GROK-REVIEW-V1 marker, re-fetch the named OPEN PR, exact current
head and base, applicable current-head CI, and cumulative material authors.
Reject stale, foreign, merged, CI-blocked or Grok-authored PRs. Read ONLY
relevant bounded diff/source and report independently evidenced findings
and test proposals in the Bot conversation.

The Bot's OneCompany App currently has READ permission only. Native GitHub
issue publication requires a separate owner-authorized Issues write permission
for onecompany-grok-worker[bot]. Do not impersonate the owner, export sessions,
create a metered xAI API key, access Codespace or self-upgrade permissions.
After OWNER has enabled issues comment capability and confirmed the actual
Bot GitHub principal, publish a single plain-text comment to issue #131:

GROK_RESULT_V1
{"version":1,"kind":"review","repo":"NTinkicht/OneCompany",
"pr":170,"head_sha":"<EXACT_CURRENT_40_HEX_SHA>",
"base_sha":"<EXACT_CURRENT_40_HEX_SHA>",
"execution_id":"<NATIVE_UNIQUE_EXECUTION_ID_AT_LEAST_12_CHARS>",
"verdict":"CHANGES_REQUIRED",
"findings":[{"severity":"MAJOR","path":"scripts/example.py",
"line":10,"description":"Specific current-head evidence"}],
"summary":"Concise independent review or test analysis."}

This example is a SHAPE, not a live assignment. No Markdown fences on the
actual Bot comment. Kinds: review or test. Verdicts: CHANGES_REQUIRED,
NO_BLOCKING_FINDINGS or INSUFFICIENT_EVIDENCE. The execution ID MUST be
per execution, NOT the repeated conversation/routine ID in the earlier
owner screenshot. If not available, output in native conversation without
fabrication; native GitHub publication cannot qualify yet.

GitHub Actions validates actual event actor, repository, PR/head/base,
green current CI, non-material authorship and dedupe by source comment ID.
It reports only NON-BINDING evidence to the PR. A test finding from a model
does not mean that the model executed deterministic tests. Actual tests
need a separate GitHub-hosted isolated tester runner.

## Development and testing activation

The existing Grok GitHub App is read-only. Developer/tester implementation
requires SEPARATE owner approval of narrowly scoped Contents/PR write,
existing native canonical WU implementation lease, exact head/base,
declared scope, generation and zero-extra-spend budget, followed by an
actual model-authored code+test PR and independent non-author review.
Never grant general write merely to enable advisory PR comments.

Reduce the native 10-minute cadence or deduplicate to stay within included
SuperGrok usage. 10-minute polls can run 1,008 times a week. No PAYG.

This source-only workflow/script/test are excluded from customer bootstraps.
Native GitHub issue-assigned event delivery remains unverified and is NOT
equated with successful provider-native scheduled reads.
