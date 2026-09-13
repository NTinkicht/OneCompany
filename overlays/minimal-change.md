# Overlay: Minimal Change

## Lens

Fix the proved problem with the smallest auditable diff that preserves surrounding contracts.

## Ask

- Which exact evidence proves the failure?
- Can the repository-pinned tool produce the correct mechanical output?
- What unrelated refactor can be excluded?
- What regression proves the fix?
- Did the patch alter semantics beyond the requested scope?

## Expected artifact

A narrow diff, a reproduction/regression check, and explicit statement of unchanged surrounding behavior.

This overlay is especially useful for CI/style/tool-generated remediation where hand-guessing canonical output is error-prone.
