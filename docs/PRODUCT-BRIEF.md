# Guided Product Brief (WU-P1-BRIEF-001)

This is the next small Create/Adopt step after `python onecompany.py onboard`. It uses the existing read-only onboarding assessment, not a separate planning database.

```sh
python onecompany.py brief --target /tmp/my-new-project --repository owner/my-new-project --json
python onecompany.py brief --target /tmp/my-new-project --repository owner/my-new-project \
  --audience "small business owners" --problem "manual intake" \
  --outcome "track incoming requests" --first-feature "create a request" \
  --save-to /tmp/my-product-brief.json
```

The default command prints a proposed, unapproved JSON draft and does not write anywhere. The owner may leave answers blank; they remain `null` and are listed in `missing_fields`. Discovered repository, stack, test, CI, branch and existing contract facts are copied from the current assessment. User-supplied audience, problem, outcome and first feature are never fabricated by the tool.

Only `--save-to` performs an explicit exclusive, private new-file write (mode 0600 where supported); an existing file or symlink is never overwritten. An unsafe onboarding assessment blocks saving. An explicit saved file **still has no approval, actor eligibility, execution lease or implementation authority**. Existing Create/Adopt targets and source policy are not modified. Never place secrets or customer-sensitive text in an issue or PR.

Next WUs #148 and #153 can *read* a saved draft, but must independently verify trusted authorization before any actual work. This command makes no model call, consumes no API credit and does not access a paid backend.
