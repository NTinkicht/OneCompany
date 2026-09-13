# Contributing to OneCompany

OneCompany should use its own operating model.

## Before changing code or governance

1. Open or identify a bounded Work Unit/issue.
2. State objective, scope, non-goals, acceptance criteria, and risk.
3. Use one canonical implementation branch/PR.
4. Record material authorship and the active implementation lease.
5. Keep changes inside the WU scope.

## Verification

At minimum run:

```bash
python scripts/validate.py
python scripts/simulate.py
python -m compileall -q scripts
```

If you add executable behavior, add deterministic tests or extend `scripts/simulate.py`.

## Review

For material changes, the final reviewer should be independent of the material author and review the exact candidate SHA. Any commit after the verdict invalidates that final exact-head gate.

## Governance changes

Changes to autonomy, financial policy, credentials/permissions, the constitution, or required merge/security gates require explicit human approval by default.

## Style

- Prefer explicit contracts over clever implicit coordination.
- Keep provider-specific adapters separate from universal policy.
- Safe defaults first; users may opt into more autonomy.
- Never commit credentials, personal data, private prompts, or provider tokens.
- Documentation must distinguish authoritative state from cached/advisory state.

## Compatibility

OneCompany should remain useful when vendors/models change. Avoid depending on an undocumented provider feature in the core specification; isolate such integrations behind adapters/examples.
