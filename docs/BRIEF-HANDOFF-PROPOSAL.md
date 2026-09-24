# Phase 1 — honest Product Brief handoff (#148)

This separate, read-only bridge consumes an **owner-filled saved DRAFT** from `python onecompany.py brief` and creates a candidate for the **existing** trusted planning/Execution Core. It never grants implementation approval, creates a canonical Work Unit, trusts caller-supplied GitHub revisions, invents acceptance criteria, acquires a lease or runs a model.

```bash
python scripts/brief_handoff_proposal.py --brief /tmp/owner-brief.json \
  --head <full-40-lowercase-head-sha> --base <full-40-lowercase-base-sha>
python -m unittest discover -s .onecompany/selftest -p 'test_brief_handoff_proposal.py'
```

The handoff now reuses the complete canonical `product_brief_diff.validate` contract and its bounded, anchored, no-follow input reader. Malformed drafts, symlinked path components, stale derived missing-answer/next-action fields, unknown authority-bearing fields (including `approved`, `run_key`, `lease_id` and `deployment_authorized`), or incomplete owner answers are refused rather than silently stripped into a plausible proposal. A normal saved owner draft still passes with `authorization: NOT_GRANTED`. The command remains read-only and does not alter the saved file or target project.

`source_refs_unverified` are displayed for discussion **only**. A trusted parent must freshly verify GitHub head/base, Product Brief approval, project identity, RunKey/generation, selected worker capability, exact lease, budget and resource locks. It must then create/approve one canonical WU using existing planning contracts. A read-only CLI cannot prove those actions occurred. This WU is independent of real Playwright localhost browser evidence (#175). KServe, OpenViking, Supermemory and ARTEMIS stay Phase 2.
