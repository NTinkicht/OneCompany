# Root-of-Trust Rotation

Root-of-trust rotation is a human-controlled recovery and governance operation. It is never an ordinary worker action and never becomes authorized merely because a candidate branch edits `.onecompany/identity.json`, actor metadata, readiness, roles, or CLI labels.

## Trust rule

Authorization is evaluated from the authenticated GitHub principal and the identity policy at the exact already-trusted revision supplied as `--trusted-ref`. Candidate policy is proposed data until it has passed protected review and been promoted to the protected default branch.

A rotation therefore has two distinct parts:

1. change the platform trust/credential boundary outside candidate-controlled repository execution; and
2. promote the matching protected identity-policy change through normal Code Owner review and required checks.

Neither half alone is sufficient.

## Preconditions

Before rotating root trust:

1. Assert the external emergency stop using `ONECOMPANY_EMERGENCY_STOP=1` or a sentinel referenced by `ONECOMPANY_EMERGENCY_STOP_FILE` if compromise is suspected.
2. Record the current protected default-branch SHA. This SHA is the authorization reference for the operation.
3. Verify branch/ruleset protection is active and non-bypassable for the governed path.
4. Verify the operator is the intended human platform principal. Do not use an actor string as evidence of identity.
5. Revoke or rotate any compromised credential using the provider/GitHub control plane. Never commit a credential or secret to the repository or ledger.

## Rotation procedure

### 1. Change platform access out of band

Using the GitHub/provider administration surface, make the required credential, collaborator, App, team, or ownership change. Keep privileges minimal. This action happens outside OneCompany candidate code.

### 2. Propose the protected identity mapping

Create a PR that updates `.onecompany/identity.json` to reflect the intended platform principal mapping. The candidate must not be used to authorize itself. Required checks and Code Owner review must evaluate it from the currently trusted base.

The PR must preserve at least one valid root principal and must not introduce ambiguous login mappings.

### 3. Independently review and promote

Require the normal protected-branch controls, including independent eligible review and the configured required check. Merge only the exact reviewed head/base pair. Once merged, the new default-branch revision becomes the authority for subsequent operations.

### 4. Append the durable rotation audit event

After promotion, append the audit event using an authenticated principal that has `root_rotation` under the trusted policy being cited:

```text
python onecompany.py ledger post \
  --type ROOT_TRUST_ROTATED \
  --trusted-ref <exact-trusted-default-branch-sha> \
  --payload-json '{"previous_principal":"<login-or-id>","new_principal":"<login-or-id>","reason":"<reason>","change_reference":"<ticket-or-pr>"}'
```

`--actor` is optional and assertion-only. It cannot grant authority. If supplied, it must match the platform-derived login or CompanyOS actor ID.

The durable event automatically records the authenticated `platform_login` and the identity-policy provenance used for authorization. Do not place tokens, secret values, private keys, recovery codes, or other credentials in the payload.

### 5. Verify and recover

Read the durable ledger and verify that `ROOT_TRUST_ROTATED` exists with the expected platform principal and policy provenance. Re-run deterministic validation and GitHub enforcement audit. Only then clear containment using an authenticated principal with `emergency_control` authority.

## Failure behavior

Rotation fails closed when the trusted ref is missing, the authenticated principal is unknown, the base-trusted identity policy cannot be established, the principal lacks `root_rotation`, or an asserted actor label disagrees with the platform identity.

If the normal repository path itself is suspected compromised, keep the external emergency stop asserted, restore a known-good protected revision through the GitHub administrative/recovery process, re-establish non-bypassable protections, and only then resume OneCompany automation.

## Emergency stop independence

Asserting the stop is intentionally permissionless and can be done outside normal worker authorization through the environment or external sentinel. Clearing the stop is privileged. This asymmetry ensures containment remains available even when normal automation or repository state cannot be trusted.
