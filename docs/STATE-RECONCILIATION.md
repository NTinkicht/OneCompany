# State Reconciliation

`.onecompany/state.json` exists to make orchestration fast. It is not allowed to become an alternate reality.

## Authoritative vs cached facts

Authoritative live facts include:

- default branch SHA;
- PR open/closed/merged state;
- PR head SHA;
- CI run/check conclusions;
- issue state;
- review comments/verdicts actually posted;
- merge result.

Cached/declared facts include:

- active role leases;
- current WU pointer;
- current gate summary;
- capacity annotations not exposed by GitHub;
- human-decision state;
- derived company state.

## Reconcile before

Always reconcile before:

- granting/failing over a write lease;
- issuing a final review request;
- accepting a merge-ready verdict;
- merging;
- selecting the next WU after a merge;
- declaring the company idle/blocked;
- resuming after a long pause or another operator/session.

## Reconciliation rules

1. If recorded PR is merged/closed, clear active PR/head/gate cache.
2. If live head differs from recorded/gated SHA, mark prior gate stale.
3. If CI status changed, update operational state.
4. If a lease references a branch/PR that no longer exists, mark it stale/released after policy review.
5. If queue says READY but dependencies are no longer satisfied, move it out of READY.
6. Never rewrite Git history to make state fit the cache.

## Tooling

`python scripts/reconcile.py` prints a proposed reconciliation using `gh` and makes no changes.

`python scripts/reconcile.py --write` updates the cache. Commit/review the change according to your project policy.

The reference reconciler intentionally covers only universally safe facts. Production projects can extend it with CI verdict parsing, labels, deployment state, capacity sources, and signed lease records.
