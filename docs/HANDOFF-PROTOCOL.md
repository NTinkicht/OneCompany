# Handoff Protocol

A handoff should allow a replacement worker to continue safely without reconstructing chat history.

## Required packet

```text
WORK UNIT: WUxx — title
ROLE: implementation / review / failure analysis / etc.
CANONICAL REPO: owner/name
BRANCH: branch
PR: #number
EXACT CURRENT HEAD: sha
BASE: branch@sha if relevant
OBJECTIVE: one sentence
NON-GOALS: bounded list
ACCEPTANCE: checklist
CURRENT CI: run/check summary
CURRENT REVIEW: reviewer, target SHA, verdict/findings
MATERIAL AUTHORS: actor IDs
BLOCKER: exact observable failure
ATTEMPTS: what has already been tried
BUDGET: relevant restrictions
SECURITY/DATA: relevant restrictions
DONE WHEN: durable artifact/state transition
```

## Failover packet

Add:

```text
PRIOR LEASE RELEASE REASON
WHY NEW ACTOR IS ELIGIBLE
WHAT MUST NOT CHANGE (same branch/PR/scope)
```

## Review packet

Add:

```text
TARGET EXACT SHA
WHY REVIEWER IS INDEPENDENT
SEVERITY THRESHOLD
REQUIRED CI CHECKS
HIGH-RISK AREAS TO INSPECT
```

## What not to send

- secrets/tokens;
- irrelevant full conversation history;
- unverified assumptions stated as facts;
- stale SHAs;
- huge logs when a precise failing excerpt/run link exists.
