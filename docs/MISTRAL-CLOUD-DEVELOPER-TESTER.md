# Mistral Code: real provider-cloud developer and test author

This is an executable GitHub Actions model-edit/publish route, not the
read-only issue #130 smoke. It uses the EXISTING included-plan Vibe Code key
and protected-main budget policy; no owner Codespace, new API provider,
PAYG/overage or transferred CLI auth session.

## Actual write path

1. A canonical Work Unit must be READY in the protected target queue, with
   the exact same PR number and branch, LOW or MEDIUM risk and 1–8 literal
   product source/test paths under examples/, src/, app/ or tests/. Broad
   globs, control-plane paths, AGENTS.md and workflow files are REFUSED.
2. One active durable native OneCompany implementation lease MUST already
   belong to actor mistral-vibe for that same WU/PR/branch, with exactly the
   expected progress head SHA and protected-main write scope. A chat or
   owner comment cannot create the lease or increase actor capacity.
3. Owner posts this exact command to the existing wake bus issue #130:

@mistral-vibe
MISTRAL_WORK_V1
pr: 123
head_sha: <EXACT_CURRENT_40_HEX_HEAD>
base_sha: <EXACT_CURRENT_40_HEX_BASE>
work_unit: WU-EXAMPLE-001
lease_id: <EXACT_ACTIVE_DURABLE_LEASE_ID>

4. A pinned GitHub-hosted Action validates owner, repo/PR/base/head/queue,
   emergency stop, active lease and USD0 budget before invoking Vibe.
   Account entitlement must return HTTP 200 and PAYG-off owner variable must
   be true. Model sees ONLY a small stage of WU-declared source/test files,
   no GH_TOKEN or PR checkout, and can use read_file, grep, edit, write_file;
   it cannot run shell/Git, merge or modify control-plane files.
5. The trusted parent verifies the model's exact declared file deltas,
   refuses extra/symlinked/binary/oversized/unchanged output, refreshes the
   lease and exact PR, and makes ONE atomic parent-SHA Git tree commit with
   Material-Author: mistral-vibe. GitHub ref update is fast-forward only.
   Model cannot independently publish arbitrary GitHub operations.
6. New HEAD requires real deterministic CI and an independent non-author
   review (ChatGPT/CodeRabbit/Grok when independently proven) before merge.
   The test-author capability is an actual model-authored test file, followed
   by a real GitHub CI run, not merely a suggested test description.
   No automatic self-approval or merge.

This first implementation lane is not an assertion that Mistral's writing,
testing and independent reviewer capabilities have been live-qualified.
Native lease admission currently refuses unqualified actor capacity; a
reviewed, isolated LOW-risk qualification WU with an authorized test lease
must be executed to promote the role. A hypothetical READY queue entry or
source PR containing this workflow does not prove a working model writer.

**Important GitHub Actions wrinkle:** GitHub generally suppresses normal
push/PR workflow recursion caused by the built-in GITHUB_TOKEN. After a
GITHUB_TOKEN-authored model commit, an independent owner-connected publisher
or reviewed explicit workflow_dispatch validation is needed for exact-head CI;
do not claim CI is green from an untriggered workflow. The next qualification
WU must prove this handoff and document the actual origin/commit/source actor.

Future Grok can receive an independent reviewer/tester assignment against
the resulting model-authored commit; neither model can be the sole reviewer of
its own material changes. Keep the existing trusted Execution Core,
RunKey/generation and lease control plane, no alternate workflow authority.
