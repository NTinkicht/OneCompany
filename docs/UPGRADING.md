# Upgrading OneCompany in an Existing Project

OneCompany upgrades are governance changes, not blind template overwrites.

## Preserve project-owned state

Before upgrading, back up and review:

- `.onecompany/config.json`;
- `.onecompany/budget.json`;
- `.onecompany/actors.json`;
- `.onecompany/readiness.json`;
- `.onecompany/routing.json` customizations;
- `.onecompany/supervision.json`;
- queue/state data that is intentionally version-controlled;
- provider-specific workflow edits;
- project-specific AGENTS/Claude/Copilot/Gemini instructions.

Never replace secrets because OneCompany does not store them in the template.

## Upgrade procedure

1. Read `CHANGELOG.md` and migration notes for the target version.
2. Compare the new control-plane schemas against local files.
3. Apply structural additions first; do not reset project policy values.
4. Review any changes to permissions, spending semantics, unattended execution, merge authority or human-only decisions as high-impact governance changes.
5. Re-run:

```bash
python onecompany.py doctor
python onecompany.py validate
python onecompany.py simulate
python onecompany.py readiness --local-probe
python onecompany.py audit-github
```

6. Re-run affected first-run acceptance drills.
7. Re-smoke any provider whose invocation/tooling template changed.
8. Promote through normal PR + independent review.

## Never auto-upgrade behavior-bearing integrations

Provider CLIs, Actions, role overlays, context compressors and wake workflows can change behavior. Pin versions where practical and promote upgrades deliberately. A passing install is not evidence that permissions, billing path or tool semantics remained safe.
