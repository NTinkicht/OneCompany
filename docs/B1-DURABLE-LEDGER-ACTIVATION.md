# Epic 0.6 B1 - Durable Team Room Ledger Activation

Parent Epic: #36  
B1 issue: #46  
Team Room: #45

## Scope

B1 activates the durable GitHub Team Room ledger that already exists in CompanyOS. It does not redesign lease/gate semantics, enable orchestration, enable automatic failover, or grant unattended implementation authority.

The authority split remains:

```text
versioned .onecompany policy/planning = approved baseline
live GitHub PR/CI/review               = execution evidence
Team Room #45                          = durable coordination facts
.onecompany/state.json                 = derived convenience cache only
```

No cache, chat history, context database, model output, or local process state can override those sources.

## Protected baseline

A3 completed when PR #44 was squash-merged to protected `main` as:

`432f4cbb75471eb84bf6eb73fe799886d7da8096`

The B1 branch `epic-0.6-b1-durable-ledger-activation` was created from exactly that commit.

## Publisher proof

B1 starts with the minimum publisher set needed to prove durable operation:

```json
"trusted_publisher_logins": ["NTinkicht"]
```

No bot or automation publisher is trusted in B1.

The publisher identity was verified by an actual append-only Team Room event before configuration was changed:

- Team Room: issue #45
- GitHub comment ID: `5689087452`
- observed GitHub publisher: `NTinkicht`
- event ID: `b1-human-publisher-proof-20260915`
- event type: `SUPERVISION_CHECK`
- logical actor: `human-owner`
- authority payload: `none`

The proof event deliberately grants no lease, gate, merge, budget, emergency-control, or human-decision authority.

## Activation configuration

`.onecompany/ledger.json`:

- `enabled: true`
- `issue_number: 45`
- `trusted_publisher_logins: ["NTinkicht"]`
- current event format remains v2
- legacy v1 cutoff remains `0`, so new legacy-v1 comments cannot become trusted events
- existing accepted event-type policy remains unchanged
- lease TTL/progress/implicit-expiry policy remains unchanged

`.onecompany/supervision.json` points coordination at Team Room #45 but supervision itself remains disabled and `observe_only`:

- GitHub Actions supervision disabled
- `may_post_team_room: false`
- `may_failover: false`
- `may_merge: false`
- ChatGPT scheduled-task mutation disabled

This intentionally separates **durable coordination availability** from **automatic coordination mutation**. B2/B3 must earn those capabilities separately.

## Live replay smoke

`.github/workflows/onecompany-ledger-read-smoke.yml` is a read-only proof surface.

Permissions:

```yaml
contents: read
issues: read
```

The workflow:

1. validates the activated ledger configuration;
2. reads/replays live Team Room #45 using `python onecompany.py ledger read --events`;
3. requires the publisher-proof event to resolve to GitHub login `NTinkicht`;
4. verifies the identity-proof event created no active lease or gate authority;
5. deletes local `.onecompany/state.json` inside the ephemeral runner;
6. replays the live ledger again;
7. requires the derived canonical view before/after cache deletion to be identical.

The smoke has no issue-write or repository-write permission and cannot append ledger events.

## Why automation publishing is deferred

The current ledger reader treats a configured trusted publisher login as trusted for accepted event types. Trusting `github-actions[bot]` prematurely would therefore create a broader publishing surface than B1 needs.

B1 intentionally trusts only the evidence-backed human publisher. A later B2 publishing slice should introduce a reviewed capability-scoped automation publisher before any bot identity is added to the trusted set.

A bot being able to publish a durable coordination event must never make it a human Code Owner, human-decision authority, or self-review authority.

## Zero-extra-spend boundary

B1 uses only repository code, GitHub issue comments, and standard GitHub Actions on the public OneCompany repository. It adds no model/API provider and no paid fallback.

The existing hard budget rules remain authoritative:

- additional monthly AI spend cap `0`;
- no paid fallback;
- no overage;
- no automatic top-up;
- no new paid vendor;
- no OpenRouter/Vertex/PAYG escape path.

## Promotion requirements

Before B1 merges:

- live read/replay smoke against Team Room #45 succeeds on the exact final head;
- `OneCompany Validate` succeeds on the exact final head;
- replay remains identical after local-cache deletion;
- no automation publisher is trusted;
- no protection, Code Owner, emergency-stop, budget or human-only decision boundary is weakened;
- all actionable review findings are resolved;
- CodeRabbit is clean on the exact final head;
- an independent human Code Owner / last-push reviewer approves the exact final head.

After protected promotion, B2 may design event-driven handoffs. OpenViking #47 remains an optional non-authoritative context experiment, and Astryx pattern work #48 remains independent of ledger authority.
