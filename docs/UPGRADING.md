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

## Pattern registry v1 -> v2 (named-source isolation)

The generic product now ships `.onecompany/patterns.json` **version 2**.
Upgrading an installed version-1 registry is a separate, reviewed data
migration; do not overwrite its project-owned pattern choices automatically.

1. Back up the installed pattern registry and compare entries with the
   version-2 schema.
2. For each obsolete, named-project `origin` or `source`, preserve genuine
   provenance in the **owning project's private history**; replace product
   registry fields with accurate generic `onecompany-native` or `adapted`
   origins and project-neutral source descriptions.
3. Change `version` to `2` only after each entry has been reviewed. The new
   schema deliberately refuses an unconverted version-1 registry.
4. Run `python onecompany.py validate` and the affected migration,
   review, bootstrap and governance tests before the normal promotion gate.

Do not treat this data migration as permission to change an installation's
workers, budgets, policy authority, project name or protected repository.

## Never auto-upgrade behavior-bearing integrations

Provider CLIs, Actions, role overlays, context compressors and wake workflows can change behavior. Pin versions where practical and promote upgrades deliberately. A passing install is not evidence that permissions, billing path or tool semantics remained safe.
