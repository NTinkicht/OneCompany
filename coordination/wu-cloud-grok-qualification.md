# WU-CLOUD-GROK-001

Issue #131. Qualify a no-Codespace, zero-extra-spend cloud Grok route.

## Implemented repository-side qualification

- `scripts/grok_cloud_qualification.py` deterministically classifies the current route.
- The provider event mechanism remains `configured=false` with no capabilities until a real Codespace-off execution is independently verified.
- Missing provider evidence is explicitly `CAPACITY_BLOCKED / PROVIDER_CLOUD_EXECUTION_NOT_VERIFIED`.
- A structurally valid evidence manifest still cannot self-promote capability; it produces `LIVE_VERIFICATION_REQUIRED`.
- Paid API use, manual-prompt dependence, owner-published evidence, wrong repository/issue, and malformed SHAs fail closed.
- Existing `scripts/grok_cloud_bridge.py` remains the authenticated GitHub-side verifier for bot-published exact-head evidence.

## True external blocker

The remaining acceptance item cannot be manufactured in repository code: the owner must complete the provider-side Grok Bot/SuperGrok GitHub connection and produce one real event-triggered execution with Codespaces and personal workstations out of the loop. No OAuth/session export, `XAI_API_KEY`, PAYG, purchased credits, or fake readiness is authorized.

Material-Author: chatgpt
