# Issue 254 - Mistral exact-head output contract hardening proposal

Status: non-canonical design/acceptance seed for issue #254. This document does not create or register a canonical Work Unit, lease, queue entry, risk record, or control-plane authority. Any delivery WU must be registered separately in the versioned `.onecompany` control plane before implementation is treated as canonical.

## Scope

Harden the trusted exact-head Mistral review packet by making the required model-output shape explicit and unambiguous, while keeping deterministic enforcement in the strict parser. The prompt cannot guarantee deterministic model output; it defines the contract that the parser validates fail-closed. No evidence requirement, review authority, or paid-fallback boundary is weakened.

## Required behavior

- The prompt must provide one exact JSON skeleton containing every parser-required key.
- The model is instructed to return exactly one JSON object with no Markdown fence, prose prefix, prose suffix, or extra keys.
- `INSUFFICIENT_EVIDENCE` must still include every required key with contract-valid values.
- Malformed, partial, fenced, prefixed, suffixed, or schema-divergent output remains fail-closed as `RESULT_CONTRACT_INVALID`.
- No parser permissiveness, review-gate weakening, paid fallback, or mutation authority is introduced.

## Regression slice

Add parser-contract cases for: exact `NO_BLOCKING_FINDINGS` payload, exact `CHANGES_REQUIRED` payload, exact `INSUFFICIENT_EVIDENCE` payload, missing required key, extra prose, fenced JSON, extra key, wrong type, and truncated JSON. Existing secret, evidence, and path guards remain unchanged.

Material-Author: chatgpt
Refs #254
