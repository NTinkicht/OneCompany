# Product Brief: turn an idea into an honest editable draft

Phase 1 WU #150 extends the already read-only Create/Adopt onboarding journey.
No AI provider, API key, lease or product decision is required to draft.

```bash
python onecompany.py onboard --target /path/to/project --repository OWNER/REPO
python onecompany.py brief --target /path/to/project --repository OWNER/REPO \
  --audience "People who need this" \
  --problem "Their specific problem" \
  --outcome "An observable useful outcome" \
  --first-feature "The smallest useful feature" \
  --constraints "Privacy/accessibility/platform limitations" --json
```

All answers are provided by the user. The command does not silently infer user
intent or invent acceptance criteria. `status: DRAFT_NOT_APPROVED`,
`write_lease_granted: false` and explicit false product/implementation/deployment
approvals remain true regardless of how complete or polished the answers are.

To export a *new* file, add `--save-to /path/to/brief-draft.json`. This is
explicitly a JSON draft export, **not** the canonical PRODUCT.md or an approved
queue item. It creates no parent folders, uses restrictive file permissions, and
refuses to overwrite any existing file or follow a destination symlink. Missing
required answers prohibit exporting a misleading completed brief. Without
`--save-to`, onboarding and brief generation are non-mutating.

Next phase: the user edits the proposed feature/acceptance criteria through
existing trusted planning/requirements schemas, reviews the resulting bounded
WU, and only then grants the normal OneCompany authorization. There is no
synthetic approval, hidden autonomy-level change or provider cost in this CLI.
