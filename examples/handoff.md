# Example Handoff Packet

```text
WORK UNIT: WU42 — consent-aware notification suppression
ROLE: CI remediation
CANONICAL REPO: example/health-app
BRANCH: wu42-consent-suppression
PR: #174
EXACT CURRENT HEAD: 7fb200c4...
OBJECTIVE: unauthorized delivery must terminate as suppressed before provider invocation
NON-GOALS: no real provider integration, no scheduler redesign
ACCEPTANCE: zero provider calls when unauthorized; terminal/no retry; privacy-safe reason; valid path unchanged
CURRENT CI: PostgreSQL integration PASS; Browser smoke PASS; Quality/build FAIL at Formatting
CURRENT REVIEW: prior exact-head review found no Medium+ logic/security issue but is BLOCKED because CI red
MATERIAL AUTHORS: chatgpt; prior mechanical commit by github-copilot
BLOCKER: repository formatter still reports one integration test file
ATTEMPTS: multiple manual wraps and one partial formatting commit did not converge
BUDGET: zero additional spend; no paid fallback/overage
SECURITY/DATA: no payload/contact/credential values in logs
DONE WHEN: repository-pinned formatter/check clean and commit pushed to same branch; CI reruns
```

This packet is intentionally enough for a replacement executor without the original chat transcript.
