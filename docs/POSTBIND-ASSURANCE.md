# Post-binding assurance (OC-P0-15)

`python onecompany.py postbind-assure --wu <id> --run-key <key> --workspace <dir> --head <40-hex> --base <40-hex> --criteria c.json --evidence e.json --manifest runtime.json --evidence-dir <dir> --approved-criteria-sha256 sha256:<hex>`

Offline and deterministic: no network, no provider call. The manifest is the `runtime-bind` output (`onecompany.runtime-binding/v1`, bare or wrapped under `manifest`) and is checked with `runtime_binding.verify`, so the WU, RunKey, workspace, head/base and build digest must already hold.

- Criteria: `{"schema": "onecompany.postbind-assurance/v1/criteria", "wu_id": ..., "criteria": [{"id": ..., "required_kinds": ["api", ...]}]}` (`required_kinds` optional; kinds are unit, api, browser, security, db).
- Evidence: `{"schema": "onecompany.postbind-assurance/v1/evidence", "items": [{"criterion_id", "kind", "result": "pass", "wu_id", "run_key", "head_sha", "base_sha", "build_digest", "artifact", "artifact_sha256"}]}`. Each item must carry exactly the manifest's binding; the artifact is a file under `--evidence-dir` whose sha256 is recomputed (no absolute paths or `..`; every path component is checked for symlinks before resolving).

`--approved-criteria-sha256` is the digest of the approved criterion set (`postbind_assurance.criteria_digest`: sorted ids plus required kinds), recorded at approval. A criteria document that differs (a dropped, added or edited criterion) is refused (exit 2), so a partial list cannot redefine success.

A criterion is covered only with a passing, exactly bound, digest-verified item of every required kind (any kind if none required). Missing, stale, mismatched, unknown-criterion, non-pass or fabricated items are named problems. The report lists `covered` and `uncovered`; uncovered is never a pass. Exit 0 only when everything is covered and no problem exists, 1 otherwise, 2 for malformed input.

Out of scope: LLM test generation, release/deployment gates.
