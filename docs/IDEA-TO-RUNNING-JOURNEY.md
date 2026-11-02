# Idea-to-running-app acceptance journey (WU-P1-E2E-001)

A copyable, no-credential, loopback-only walk-through. `.onecompany/selftest/test_idea_to_running_journey.py` runs these exact commands against a disposable git project and asserts each boundary.

1. **Proposed only** - `python onecompany.py brief --target P --repository OWNER/REPO --audience ... --problem ... --outcome ... --first-feature ... --save-to brief.json`. Missing answers stay missing; a saved brief is not approval and carries no RunKey or lease.
2. **Owner must approve** - `python onecompany.py approve-brief --target P --repository OWNER/REPO --brief brief.json --head H --base B` previews and changes nothing. Only `--approve-wu <id> --owner-ack --planning-ref <id> --write-scope <glob>` admits one READY WU, still without lease or RunKey.
3. **Actually executed** - `python onecompany.py runtime-bind --wu <id> --run-key <key> --workspace P --head H --base B --ci success --tests passed --out runtime.json` starts the real fixture app on 127.0.0.1, runs health plus CRUD, stops it and verifies the port is closed. Absent or failing CI/tests, a moved head or another RunKey yield `blocked`, never `ready_to_preview`. The label stays "local demo, not production-qualified".
4. **Evidence per criterion** - `python onecompany.py postbind-assure ...` (see POSTBIND-ASSURANCE.md) covers a criterion only with exactly bound, digest-verified evidence; absent, stale, failing or forged items are uncovered, and a dropped criterion is refused.

Existing project files are preserved byte-for-byte. Nothing is deployed, no provider is called, no spend or credential is involved. Independent non-author review and exact-head CI still gate any merge.
