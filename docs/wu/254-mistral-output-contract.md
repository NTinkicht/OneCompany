# WU 254 - Mistral exact-head output contract hardening

## Scope

Harden the trusted exact-head Mistral review packet so model output is deterministic without weakening the strict parser, evidence requirements, review authority, or paid-fallback boundary.

## Required behavior

- The prompt must provide one exact JSON skeleton containing every parser-required key.
- The model must return exactly one JSON object with no Markdown fence, prose prefix, prose suffix, or extra keys.
- `INSUFFICIENT_EVIDENCE` must still include every required key with contract-valid values.
- Malformed, partial, fenced, prefixed, suffixed, or schema-divergent output remains fail-closed as `RESULT_CONTRACT_INVALID`.
- No parser permissiveness, review-gate weakening, paid fallback, or mutation authority is introduced.

## Regression slice

Add deterministic cases for: exact PASS payload, exact FAIL payload, exact INSUFFICIENT_EVIDENCE payload, missing required key, extra prose, fenced JSON, extra key, wrong type, and truncated JSON. Existing secret/evidence/path guards remain unchanged.

Material-Author: chatgpt
Refs #254
