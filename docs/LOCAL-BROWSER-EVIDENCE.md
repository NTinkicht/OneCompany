# Phase 1 — optional REAL browser smoke (#175)

OneCompany has a genuine local HTTP checklist and deterministic API tests. This **additional** evidence is only PASS after a real headless Chromium Playwright session sees the DOM and adds, completes and deletes an item against the disposable loopback server.

```bash
# Install Python Playwright + Chromium only if available under your existing
# approved local/CI budget; the normal OneCompany validation does not install it.
python examples/vertical-slice/app.py --port 8765
python scripts/local_browser_evidence.py --revision <full-clean-checkout-HEAD-SHA> \\
  --url http://127.0.0.1:8765/
python -m unittest discover -s .onecompany/selftest -p 'test_local_browser_evidence.py'
```

The runner fails closed on non-loopback URLs, wrong/dirty checkout, failed health, missing Playwright/Chromium and any DOM action failure. Its self-tests exercise refusal boundaries, **not** an actual browser. Do not count green source CI as browser qualification: attach real browser-run evidence and exact SHA before claiming Phase 1 Playwright complete. No remote access, screenshot, credentials, deployment, approval or spending change; KServe, OpenViking, Supermemory and ARTEMIS remain Phase 2.
