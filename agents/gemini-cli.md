# Gemini CLI Adapter Guide

Use with `UNIVERSAL-CONTRACT.md`.

## Good fits
Repository intelligence, broad regression scouting, local CLI analysis, research, and implementation when safely configured.

## Operating notes
- Prefer read-only unattended permissions for scouting unless a write lease is explicit.
- Scrub/avoid sensitive terminal output in logs and handoffs.
- Free allowance is still capacity-limited; exhaustion should trigger routing, not paid API/Vertex fallback unless budget policy allows it.
- Unattended runtime reliability should be proven with a dummy/bounded task before critical-path use.

## Recommended roles
Repository Intelligence & Regression Scout; eligible implementer when configured and leased.
