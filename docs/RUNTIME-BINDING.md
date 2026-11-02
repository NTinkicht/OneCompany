# Runtime binding (OC-P0-14, first slice)

`python onecompany.py runtime-bind --wu <id> --run-key <key> --workspace <dir> --head <40-hex> --base <40-hex> [--ci success] [--tests passed] [--out file.json]`

Resolves the app from the supplied `--workspace` (it must be a git checkout whose `HEAD` equals `--head`, with `--base` an ancestor of it and the app source uncommitted-change free), then starts the disposable `examples/vertical-slice` app on an ephemeral `127.0.0.1` port, captures `/health` and a create/update/list/delete round trip, stops it, verifies the server thread ended and the port is closed, and writes an evidence manifest (`onecompany.runtime-binding/v1`) recording WU id, RunKey, workspace, exact head/base SHA, build digest (sha256 of the app source), start/stop times and cleanup result.

`verify` refuses a manifest with any missing field or any mismatch against the expected WU, RunKey, workspace, head or base, a changed build digest, failed health or CRUD evidence, unverified cleanup (each nested status is checked, not just the aggregate `ok` flag), a workspace that is not the exact head checkout, or `production_qualified` other than `false`. `project` returns `ready_to_preview` only when verification passes against the **current** head/base AND CI is `success` AND tests passed; otherwise `blocked` with reasons. The label is always "local demo, not production-qualified".

Exit codes: 0 ready, 1 blocked, 2 refused input. Loopback only, no credentials, no deployment.

Out of scope for this slice: browser evidence, per-criterion assurance (OC-P0-15), public hosting.
