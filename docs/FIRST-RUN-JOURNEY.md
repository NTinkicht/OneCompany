# Guided first-run Create/Adopt continuation

Use `python onecompany.py journey --target /path/to/project --repository OWNER/REPO` to learn what OneCompany has **actually discovered** and what the owner needs to do next. Add `--json` for a machine-readable, read-only view.

There is one canonical intake: `scripts/onboard.py`, and one owner-filled Product Brief: `scripts/product_brief.py`. This new command reuses both; it is not a second planning store, lease system or AI-generated product specification.

## A first session

1. For an empty target, run `python onecompany.py journey --target /tmp/future-product --repository demo/future-product`. Its stage is `NEEDS_PRODUCT_BRIEF`, with the next command shown as an **argv array** (not shell-interpolated input). Existing projects use the same command and show detected stack, test directories, CI and contract files.
2. Collect the owner answers with `python onecompany.py brief --target /tmp/future-product --repository demo/future-product --audience "..." --problem "..." --outcome "..." --first-feature "..." --save-to /tmp/owner-brief.json`. The destination is explicit, exclusive and restrictive. Saving a draft does **not** approve implementation.
3. Run `python onecompany.py journey --target /tmp/future-product --repository demo/future-product --brief /tmp/owner-brief.json --json`. If the saved brief matches the current assessment and all required answers exist, the stage is `PROPOSAL_READY_NOT_APPROVED`. It suggests `scripts/brief_handoff_proposal.py` with placeholders for **live refs that must be checked by the trusted planning parent**. The proposal remains unauthorized, and the existing `python onecompany.py plan brief-handoff` route can consume it read-only after exact-ref validation.

The command rejects a saved brief larger than 16 KiB, a symlinked input, stale repository/path/branch/assets, changed approval flags, injected acceptance criteria, lease, RunKey, other authority fields, malformed owner answers or discovery blockers. A changed existing repository must be reassessed and its owner brief reviewed again rather than silently trusting stale facts.

**No repository is created, adopted, written to, built, deployed or authorized by `journey`.** No provider is invoked; no AI capacity, independence, browser execution or deployment readiness is inferred. Once the owner has reviewed the proposed feature and acceptance criteria, the existing trusted planning and Execution Core authority process—not this view—decides whether to admit a bounded Work Unit. The independent browser evidence WU #175/#177 and full vertical acceptance #153 remain separate.
