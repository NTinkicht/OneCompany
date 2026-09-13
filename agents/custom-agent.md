# Custom / Local Agent Adapter Template

Copy this guide for any new worker.

## Identity
- Actor ID:
- Provider/runtime:
- Execution mode:
- Cost class:

## Capabilities
-

## Permissions
- Repository read:
- Branch write:
- PR/issues:
- Actions/checks:
- Merge:
- Secrets/admin: normally none

## Data boundary
What data may this worker receive? What must be redacted?

## Capacity behavior
How is unavailable/quota-limited state detected? Is paid fallback possible and, if so, is it forbidden by default?

## Authorship/gating
Confirm `may_independently_gate_own_material_authorship=false` unless a human explicitly adopts a different governance model.

## Validation task
Before production use, give the worker a harmless bounded task and verify it produces the expected durable artifact without scope/permission/budget violations.
