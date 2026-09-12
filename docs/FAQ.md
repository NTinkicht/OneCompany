# FAQ

## Do I need six AI subscriptions?
No. OneCompany describes company roles and contracts. A minimal setup can be one human, one write-capable AI, one independent reviewer, and deterministic CI.

## Is OneCompany an agent framework?
It is broader: a governance/orchestration operating system around repositories. Existing agents/frameworks can plug into worker roles.

## Why GitHub as source of truth?
Commits, PR heads, CI results, issues, and merges are durable and queryable. Chat context is useful but too easy to lose or contradict.

## Why only one implementer?
One *canonical stream* per WU prevents duplicate/conflicting work. Multiple agents can still analyze read-only, design tests, or review.

## Can the same AI implement one WU and review another?
Yes. Independence is evaluated per target head/authorship, not as a permanent brand restriction.

## What if my best model hits quota?
Fail over the lease to an eligible worker on the same branch/PR. If policy forbids paid fallback and no eligible worker remains, block visibly.

## Why not just let CI merge?
CI catches deterministic classes of failure. Security, architecture, acceptance interpretation, and subtle concurrency/privacy issues often need independent contextual review.

## Does a formatting-only commit invalidate review?
By safest default, yes: new SHA means refreshed exact-head confirmation. Projects may define a narrower mechanically verified exception, but it should be explicit.

## Is `state.json` authoritative?
No. It is a cache for coordination. Live GitHub wins on conflict.

## Can I use Slack/Discord?
Yes, as attention/culture layers. Avoid making them competing sources of repository truth.

## Can OneCompany spend money autonomously?
Only if explicit budget policy permits the exact class of spend. Safe reference configuration forbids additional spend.
