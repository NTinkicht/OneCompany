# Brief approval (`approve-brief`)

`python onecompany.py approve-brief` is the owner-acknowledged step between a saved Product Brief and a bounded work unit. It is local and offline: no network, provider call, credential read or spend.

```
python onecompany.py approve-brief --target T --repository O/R --brief B.json \
  --head SHA --base SHA --approve-wu WU-ID --owner-ack \
  --planning-ref EPIC-ID --write-scope "src/**" --write-scope "tests/**"
```

Without **both** `--approve-wu` and `--owner-ack` it prints what would be admitted and changes nothing (exit 2).

With both, it re-opens the brief securely (regular file, no symlink, at most 16 KiB), re-assesses the target exactly as `journey` does, and appends **one** `READY` work unit to the target's existing `.onecompany/queue.json`. Acceptance criteria are the owner's `outcome` answer verbatim, never generated. The unit traces to an existing portfolio entity (`--planning-ref`, with the reverse `delivers` link added) and carries the owner-declared `--write-scope` (relative, no traversal, not match-all); both are required to apply. The unit carries no lease, RunKey, branch or dispatch.

The unit records `brief_approval` (brief SHA-256, head, base). A second identical run reports the existing unit and writes nothing; changing the brief, head or base against an existing id is refused.

Refusals (stderr `REFUSED: <reason>`): `COMPLETE_VALIDATED_BRIEF_REQUIRED`, `SAVED_BRIEF_STALE_OR_AUTHORITY_BEARING` (stale repository/path/branch, forged approval, RunKey, lease or injected criteria), `SAVED_BRIEF_TOO_LARGE`, `SAVED_BRIEF_FILE_REQUIRED`, `EXACT_DISTINCT_REVISIONS_REQUIRED`, `UNKNOWN_WU_ID`, `WU_ID_EXISTS_WITH_DIFFERENT_APPROVAL`, `ACTIVE_WU_STREAM_PRESENT`, `TARGET_QUEUE_NOT_FOUND`, `TARGET_QUEUE_UNSAFE` (including a symlinked `.onecompany`), `PLANNING_REF_REQUIRED`, `UNKNOWN_PLANNING_REF`, `WRITE_SCOPE_REQUIRED`, `WRITE_SCOPE_INVALID`.

The whole read/check/write runs under an exclusive lock on `.onecompany/.brief-approval.lock` and all file access is anchored to a verified directory descriptor.

Out of scope: leases, dispatch, worker runs, merge logic, autonomy-level changes. Head and base are caller-supplied; a trusted parent still reconciles them against live refs before any execution.
