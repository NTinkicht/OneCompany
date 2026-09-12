# Configure a Custom / Local Agent

OneCompany is provider-neutral. A new agent becomes routable only after its identity, cost, permissions, capabilities, and execution path are explicit and smoke-tested.

## 1. Give it one stable actor ID

Add one entry to `.onecompany/actors.json`. Do not create separate actor identities merely for “review mode” and “coding mode” if the same underlying worker/material authorship applies.

Declare only potential capabilities the runtime genuinely supports.

## 2. Classify cost before execution

Choose a cost class compatible with `.onecompany/budget.json`. If pricing/billing state is unknown, fail closed. Local compute is not automatically free if it incurs cloud/GPU/hosted costs.

## 3. Define authentication and secret storage

Document:

- authentication method;
- where credentials live;
- repository scope;
- expiration/rotation behavior;
- whether unattended execution uses a different credential path.

Never store raw credentials in the repository or readiness registry.

## 4. Define permissions

Separate:

```text
read
write to canonical branch
publish review
merge
admin/security settings
external network/resources
```

The default should be the smallest set needed. Scouting normally needs only read.

## 5. Create an adapter guide

Copy `agents/custom-agent.md` and document strengths, failure modes, authorship identity, and any special execution constraints. If the agent has a native instruction-file convention, create the smallest adapter that points back to `AGENTS.md`/the universal contract.

## 6. Smoke-test by capability

At minimum:

- read a known policy/source file;
- prove repository remains unchanged after a read-only task;
- if implementation is desired, make a harmless change on a disposable branch and run CI;
- if review is desired, review a non-authored exact SHA and publish a durable artifact;
- if merge is desired, test expected-head-protected merge in an approved sandbox/setup WU;
- if unattended operation is desired, test timeout, log redaction, permissions, and stop behavior.

Record only non-secret evidence in `.onecompany/readiness.json`.

## 7. Shadow first when risk is high

If the new agent/router/compressor/reviewer can influence security, merge, migrations, or production behavior, start it in read-only/shadow mode. Compare its output with the authoritative path before promotion.

## 8. Independent review

If the new runtime materially authors the candidate head, the same actor cannot become independent simply by changing model/prompt/persona inside that runtime unless governance explicitly defines them as genuinely independent actors with separate provenance and capacity.
