# ntk-reviewer engine: Mistral or Codex

`ntk-reviewer` is the one reviewer whose approval the main-branch rule of OneCompany, Tabibi and
veritas-atlas counts. Where its verdict comes from is chosen by the OneCompany **repository
variable** `REVIEWER_ENGINE`:

| Value | Verdict source | Model calls |
|---|---|---|
| unset, empty, `mistral` or anything else | one Mistral Vibe call on the PR diff (the original setup) | 1 per head |
| `codex` | the Codex GitHub reviewer's (`chatgpt-codex-connector[bot]`) completed review | none |

Every other gate is identical in both engines:
- exact head and base;
- green required CI on the exact head;
- the control-plane floor: never approve `.github/**`, CODEOWNERS or listed paths;
- stale-review dismissal when the head or base moves;
- no approval of work the engine's own vendor authored (`Material-Author: mistral…` for Mistral, `codex`/`chatgpt`/`openai…` for Codex).

## When the Codex engine approves

All of these must hold:

1. **Codex reviewed this code after the current base existed.** The Codex bot's `codex-review-state:v1` comment, or its native review, names a commit with `status: completed`. The review completed after the current base commit was made: a moved base stales the gate (`AGENTS.md`), so every base move needs a fresh Codex review. The reviewed commit is either:
   - the exact head; or
   - an ancestor of the head where every later commit is a merge and the PR's per-file diff is byte-identical (only "Update branch" merges since).
2. **No review conversation is open.** This uses GitHub's live thread state, not Codex's own `has_unresolved_findings` flag, which does not update after fixes.
3. **The common gates pass:** CI green, no control-plane paths, head and base unchanged while posting.

If Codex has not reviewed the current code against the current base, because fixes were pushed or main moved, the reviewer posts `@codex review` once for that head and base and waits. It finds its own earlier request comments to avoid asking twice. If Codex does not answer requests from the reviewer app, the writer or the owner can post `@codex review` on the PR.

Codex reviews count against the owner's ChatGPT plan allowance for Codex code review. Keep "Use credits for reviews" **off** in Codex settings, so a used-up allowance pauses reviews instead of spending money.

## Switch to Codex (owner)

1. In Codex settings, turn on **Automatic reviews** for `NTinkicht/OneCompany`, `NTinkicht/Tabibi` and `NTinkicht/veritas-atlas`, and keep credits off.
2. OneCompany → Settings → Secrets and variables → Actions → Variables → add `REVIEWER_ENGINE` = `codex`.
3. OneCompany → Actions → **ntk-reviewer** → **Enable workflow**, if it was disabled.

`REVIEWER_ENABLED`, `REVIEWER_MODE`, `MISTRAL_API_KEY`, the `reviewer` environment and the App credentials stay exactly as they are.

## Switch back to Mistral (owner)

1. Check in the Mistral console that the Vibe budget is available again.
2. OneCompany → Settings → Secrets and variables → Actions → Variables → **delete** `REVIEWER_ENGINE`, or set it to `mistral`.
3. Make sure the **ntk-reviewer** workflow is enabled.

The next run reviews every open PR with Mistral again. An approval Codex-mode already posted for the current head and base stays valid, as for any approval, and is dismissed as usual when the head or base moves.

## Pause the reviewer

OneCompany → Actions → **ntk-reviewer** → **Disable workflow** (or set `REVIEWER_ENABLED` to anything but `true`). Re-enable the same way. No PR can merge while it is paused, because the merge rule still requires its approval.
