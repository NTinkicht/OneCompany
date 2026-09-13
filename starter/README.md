# Starter Usage

The canonical starter is the repository itself. Run from a OneCompany checkout:

```bash
python scripts/bootstrap.py --target /path/to/your/project
```

The bootstrap intentionally refuses to overwrite existing files by default. Review conflicts instead of forcing a template over project-specific policy.

After copying:

1. edit `.onecompany/config.json` project/repository name;
2. set the budget before connecting workers;
3. enable only actors that are actually configured;
4. run `python scripts/doctor.py` and `python scripts/validate.py`;
5. begin at L1/L2 unless you already have mature independent gates and incident controls.
