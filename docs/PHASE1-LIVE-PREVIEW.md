# View the disposable local app

From the OneCompany **source checkout**, run:

```bash
python onecompany.py preview-local --port 0
```

The existing example app starts on `127.0.0.1` and prints its actual local URL. Open that URL in your browser, add/complete/delete a checklist item, then press **Ctrl+C**. The app uses in-memory SQLite; all items disappear when the process stops. The request Host and Origin restrictions, Content Security Policy and no-store headers come from the existing app. Choose a specific local port with `--port 8765` if desired; port `0` requests a free ephemeral local port.

This is a **sign-inless disposable demonstration**, not an app generated from your idea, a public preview, a customer-data store or a deployment. Do not enter real customer/patient information. It does not approve a Product Brief, WU, RunKey, lease, trusted GitHub revision, CI gate, independent review, or browser-evidence qualification. For an actual Create/Adopt-to-disposable-HTTP proof after you save a complete owner draft, use `python onecompany.py demo` instead.

The `preview-local` app helper belongs to the OneCompany source checkout, not to an installed target project's OneCompany bootstrap; the entrypoint fails clearly when the helper is absent. No new provider, credential, network exposure, or extra AI spend. Phase2 KServe, OpenViking, Supermemory and ARTEMIS remain planned.
