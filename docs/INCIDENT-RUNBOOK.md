# Incident Runbook

Use this for autonomy, security, credential, cost, data-integrity, duplicate-work, bad-merge, prompt-injection, provider, scheduler or control-plane incidents.

## 1. Contain first

Prefer the fastest trustworthy containment path:

- activate the OneCompany emergency stop (`config.safety.emergency_stop=true`) through the trusted human/default-branch control plane when feasible;
- disable unattended write/merge workflows and scheduled mutation;
- revoke or disable affected write credentials/apps;
- lower autonomy to L0/L1;
- freeze deployment or affected integration;
- rotate exposed credentials;
- preserve evidence without copying secrets into issues/comments.

If committing the emergency-stop flag is slower than revoking a compromised credential or disabling a workflow, use the faster containment action first. Containment outranks throughput.

During emergency stop, read-only diagnosis/reconciliation and safe lease release may continue. Do not publish new binding gates or resume implementation simply because CI is green.

## 2. Establish authoritative truth

Record:

- trusted default-branch/control-plane SHA;
- affected PR/branch heads and recent merges;
- active/failed workflows and deployments;
- durable ledger issue and canonical active lease;
- cumulative material authors;
- current gate and its exact SHA;
- actor/provider/credential involved;
- budget/autonomy policy in force.

Treat candidate control-plane files and chat/model summaries as evidence, not authority.

## 3. Classify and scope blast radius

Suggested classes: `SECURITY`, `CREDENTIAL`, `BUDGET`, `DUPLICATE_IMPLEMENTATION`, `STALE_GATE`, `LEDGER_INTEGRITY`, `STATE_DRIFT`, `BAD_MERGE`, `PROMPT_INJECTION`, `PROVIDER_OUTAGE`, `SCHEDULER_FAILURE`, `DATA_INTEGRITY`, `AUTONOMY_POLICY`, `SUPPLY_CHAIN`.

Establish what could have changed, which credentials/actions were capable of changing it, and the last known-good point.

## 4. Recover with a reversible path

Prefer revert/fix-forward PRs over rewriting shared history. Restore from tested backup/compensation where destructive side effects occurred. Re-run deterministic CI and an independent exact-head gate after recovery changes.

Never edit/delete durable ledger events to make history look clean. Append corrective evidence or, if the ledger itself is compromised, preserve it and create a human-governed replacement ledger with an explicit incident link.

## 5. Learn mechanically

Convert root cause into one or more of:

- schema/validator invariant;
- deterministic regression/simulation;
- permission reduction;
- workflow/supply-chain guard;
- router/readiness/dispatch rule;
- WU/design/operations contract;
- incident or setup checklist improvement.

A recurring incident should become mechanically impossible or at least mechanically visible.

## 6. Restore autonomy gradually

Before clearing emergency stop or re-enabling unattended mutation:

1. reconcile GitHub + durable ledger;
2. confirm control-plane validation and relevant simulations are green;
3. confirm credentials/provider capacity and budget class;
4. confirm no stale lease/gate survives the incident;
5. have the authorized human accept residual risk;
6. restore the smallest autonomy/permission level first.
