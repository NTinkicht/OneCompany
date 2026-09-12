# Configure the Human Owner

OneCompany treats the human owner as an optional first-class actor so L1/L2 can use a real human independent gate/merge path without pretending an AI performed it.

## 1. Decide the human's active roles

A human owner may perform planning, implementation, review, security review, reconciliation, or merge. Verify only the capabilities you actually want routing to consider.

A common L1/L2 posture is:

```text
verified_capabilities: code_review, security_review, merge_execution
repository_access: read=true, review=true, merge=true
write=false unless the owner also implements
```

This keeps the human available as a safety gate without making them the default implementation worker.

## 2. Verify GitHub access

Confirm the owner account can read the repository, inspect the exact PR head/checks, publish a durable review, and merge when intended. Record non-secret evidence in `.onecompany/readiness.json` with surface `human_github`.

## 3. Authorship still matters

A human who materially implements/remediates the candidate is a material author and cannot then be counted as the independent final gate for that same head. The same separation-of-powers rule applies to humans and AIs.

## 4. Enable only after readiness is recorded

Set `human-owner.configured=true` and `enabled=true` in `.onecompany/actors.json` only after the corresponding readiness record is `ready`/`degraded` and the intended capabilities/access are verified.

## 5. Human authority versus routine coordination

Being owner does not mean the human must act as scheduler, heartbeat monitor, or merge coordinator forever. The objective is to reserve the human for decisions and gates that genuinely require human authority while allowing the company to automate routine coordination as autonomy matures.
