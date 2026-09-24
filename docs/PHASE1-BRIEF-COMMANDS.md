# Saved Product Brief commands — first-run review (WU #207)

Use the **same OneCompany entry point** throughout the read-only owner draft lifecycle. The four commands below delegate to existing, tested helpers; no second planner, validator, authority store or service is created.

```bash
# From a OneCompany SOURCE checkout: collect owner intent and export a NEW draft.
python onecompany.py brief --target /tmp/future-product --repository OWNER/REPO \
  --audience "Families" --problem "Missed appointments" \
  --outcome "See upcoming appointments" --first-feature "Local checklist" \
  --constraints "No sensitive records" --save-to /tmp/owner-draft-v1.json

# Read a previously exported draft and inspect answers without editing it.
python onecompany.py brief-resume /tmp/owner-draft-v1.json --json
python onecompany.py brief-status /tmp/owner-draft-v1.json --require-complete
python onecompany.py brief-validate /tmp/owner-draft-v1.json

# After creating an independent SECOND export using the same project identity:
python onecompany.py brief-diff /tmp/owner-draft-v1.json /tmp/owner-draft-v2.json --json

# Planning handoff remains a proposal, never permission. Set HEAD_SHA and
# BASE_SHA to distinct full 40-character lowercase commit SHAs before running:
python onecompany.py brief-handoff --brief /tmp/owner-draft-v2.json \
  --head "$HEAD_SHA" --base "$BASE_SHA"
```

**Output meanings.** `brief-resume` displays completed/missing required owner answers; `brief-diff` shows changes only between drafts of the **same discovered project**. `brief-status --require-complete` exits 3 when owner answers are incomplete, 2 when blocked or malformed, and 0 when complete. Without `--require-complete`, an honest incomplete draft can exit 0. `brief-validate` returns 0 only for a complete, structurally acceptable unapproved draft; refused/incomplete drafts return 2. `brief-diff` and `brief-resume` reject malformed/authority-bearing drafts, unsafe symlinks and oversized files. Some secure draft-reading features require POSIX no-follow file descriptors; unsupported installations refuse rather than silently weaken checks.

These four **source-checkout-only** convenience routes do not edit drafts or target repositories. A Product Brief is `DRAFT_NOT_APPROVED` even when all answers are supplied. Comparison, validity and readiness are **not** owner approval, acceptance criteria, a canonical Work Unit, a lease, verified GitHub revision, independent review, provider authorization or deployment permission. The existing trusted planning and execution gates still apply; no additional AI spending occurs.

Check implementation and refusal paths:

```bash
python -m unittest discover -s .onecompany/selftest -p 'test_onecompany_brief_commands.py'
```

Phase-2 optional KServe, OpenViking, Supermemory and ARTEMIS capabilities remain separately planned.
