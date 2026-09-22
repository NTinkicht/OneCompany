# Phase 1 — optional REAL browser smoke (#175)

OneCompany has a genuine disposable local HTTP checklist and deterministic API tests. The Playwright evidence runner reports PASS only when a **real headless Chromium session** sees the DOM and adds, completes and deletes an item against the loopback server on a clean exact checkout revision.

## GitHub-hosted real browser qualification

The `OneCompany Playwright Local Evidence` Actions workflow executes on this feature PR. It checks out the PR's exact head, installs pinned Python Playwright and Chromium into an ephemeral GitHub-hosted runner, starts `examples/vertical-slice/app.py` on `127.0.0.1:8765`, waits for its real health endpoint, invokes `scripts/local_browser_evidence.py`, checks the JSON browser flow and exact revision, and uploads a metadata-only evidence artifact. It never receives application credentials or external user data. **Only a completed successful workflow on the live PR head, together with its actual artifact, supports the real-browser qualification claim.**

The ordinary `OneCompany Validate` and `OneCompany Handoff Supervision` workflows exercise source and governance invariants but do not replace the real browser run. A mock self-test passing is not Chromium evidence.

## Optional local reproduction

```bash
# Install only if allowed under the current approved local/CI resource budget.
python -m pip install 'playwright==1.55.0'
python -m playwright install chromium
# In terminal one:
python examples/vertical-slice/app.py --port 8765
# In terminal two, on an unmodified clean checkout:
REVISION=$(git rev-parse --verify HEAD)
python scripts/local_browser_evidence.py --revision "$REVISION" --url http://127.0.0.1:8765/
python -m unittest discover -s .onecompany/selftest -p 'test_local_browser_evidence.py'
```

The runner refuses non-loopback URLs, dirty/stale/wrong checkout, failed health, missing Playwright/Chromium and any failed DOM action. It does not capture screenshots or authorize deployment. No provider inference, production traffic or new credentials. KServe, OpenViking, Supermemory and ARTEMIS remain Phase 2.
