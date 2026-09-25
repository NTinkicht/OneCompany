# Mission Control: safe local input boundary (WU #209)

The Phase-1 dashboard accepts only a bounded canonical, **unapproved** local projection produced by the existing `scripts/mission_control_projection.py` or a precomposed dashboard projection from `scripts/phase1_mission_evidence.py`. An optional `--journey` file is the existing read-only first-run journey; it cannot grant approval. The projected readiness, checks and any localhost preview URL remain **unverified display information**, not binding execution evidence.

```bash
python onecompany.py mission-control \
  --input /tmp/canonical-projection.json \
  --journey /tmp/canonical-first-run-journey.json --port 0
# The program prints its actual 127.0.0.1 ephemeral URL; Ctrl+C stops it.
```

When passing an already-composed dashboard projection (`onecompany.mission-control-dashboard.phase1.v1`), omit `--journey`; composition happened upstream. The regular producer projection is `onecompany.mission-control.phase1.v1`. Only canonical revision/check/approval envelopes are admitted; a hand-made illustrative UI mock without those fields is not valid CLI input. Calling the existing `render()` function in unit tests does not create execution authority.

**Input safeguards:** the CLI uses bounded regular-file reads with no-follow directory and final-file descriptors on POSIX. Symlinked parents and files, named pipes, nonregular/oversized inputs, malformed JSON and nested projections beyond 128 object/array levels (even below the Python parser's recursion limit), duplicate keys including Unicode-escaped names, NaN/Infinity constants or numeric overflow (`1e9999`), **nested or top-level** extra owner-approval, RunKey, lease, work-unit, deployment or spending assertions, malformed canonical checks, `PASS` without `exact_revision=true`, inconsistent READY/BLOCKED readiness versus the bounded execution/check states, and out-of-range ports are refused before the server is started. If the host lacks required secure-open flags, the CLI refuses instead of using unsafe fallback. No output file or customer project is modified. Ports 0–65535 are supported (0 selects an available localhost-only port); negative or larger values return status 2.

```bash
python -m unittest discover -s .onecompany/selftest -p 'test_mission_control_input_guard.py'
```

The dashboard still binds only to `127.0.0.1`, checks Host, escapes displayed values and restricts preview addresses to localhost. Neither the dashboard nor a caller-controlled JSON file verifies live GitHub SHA/CI/review, approves a Work Unit, grants a lease or RunKey, authorizes spending or deploys. Phase-2 optional KServe, OpenViking, Supermemory and ARTEMIS are unaffected.
