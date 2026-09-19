# Pattern: Pinned Upstream + Reviewed Promotion

## Problem

External prompts, agent libraries, CLIs, or context tools can change behavior upstream. A floating install can silently change the autonomous company's behavior without any local review.

## Pattern

For behavior-bearing external components:

1. record upstream repository and license;
2. pin an immutable commit/release/digest when practical;
3. verify provenance at runtime for high-impact tooling;
4. treat upstream changes as opt-in;
5. inspect the diff/changelog;
6. adapt rather than blindly copy;
7. promote through a normal reviewed governance PR.

## Generic examples

- Pin an optional role library to an immutable approved revision.
- Require a proposed context compressor to match reviewed provenance in shadow mode.

## What to pin

Prioritize components that can change prompts, routing, review behavior, code generation, compression, security decisions, or execution permissions. Ordinary transitive dependencies may be governed by the project's normal dependency/update policy instead.
