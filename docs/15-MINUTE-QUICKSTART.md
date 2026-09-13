# 15-Minute Quick Start

This path gets an existing GitHub project to safe **L1/L2**, not full unattended L5.

## Minute 0-3 — Copy OneCompany

From a OneCompany checkout:

```bash
python onecompany.py bootstrap --target /path/to/project
```

If files already exist, the bootstrap refuses to overwrite them. Merge intentionally.

## Minute 3-6 — Set identity and budget

Edit:

```text
.onecompany/config.json
.onecompany/budget.json
```

Set project name/repository/default branch. Keep additional spend at `0` unless you explicitly want metered usage.

## Minute 6-9 — Register workers

In `.onecompany/actors.json`, set `enabled=true` and `configured=true` only for workers that are actually connected and permitted. Leave all others disabled.

For a minimal setup, you need:

- one eligible implementer route;
- one independent reviewer route (may be human at first);
- deterministic CI.

## Minute 9-11 — Verify environment

```bash
python onecompany.py doctor
python onecompany.py validate
python onecompany.py simulate
```

Fix any blocking error before autonomous writes.

## Minute 11-13 — Define first WU

Create an issue from `.github/ISSUE_TEMPLATE/work-unit.md`. Choose something bounded and low/medium risk. Write acceptance tests/criteria before granting a lease.

## Minute 13-15 — Start safely

- grant one implementation lease;
- use one branch/PR;
- keep human merge authority at first;
- require green CI;
- record material authorship;
- obtain non-author exact-head review where configured.

After several clean WUs, use `docs/AUTONOMY-LEVELS.md` and `docs/SIMULATION.md` before moving to L3/L4.
