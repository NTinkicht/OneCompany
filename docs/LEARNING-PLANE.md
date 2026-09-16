# OneCompany shared learning plane

The learning plane is a repo-native, reviewable memory for reusable engineering lessons. It is designed to help later workers anticipate previously observed failure classes without turning reviewer/model memory into authority.

## Canonical store

`.onecompany/knowledge/` is canonical and works without any external database or embedding service:

- `candidate/` - extracted claims with provenance, not injected into normal work;
- `current/` - validated advisory lessons eligible for bounded planning/preflight context;
- `archived/` - retired/superseded history, excluded from normal context;
- `manifest.json` - lifecycle, privacy, authority and context-bound rules.

Optional semantic indexes such as a future OpenViking experiment may index this store, but are derived/rebuildable only.

## Commands

Validate the canonical store:

```bash
python onecompany.py knowledge validate
```

Retrieve bounded current lessons:

```bash
python onecompany.py knowledge retrieve --tag security --query "filesystem publication"
```

Build an advisory preflight:

```bash
python onecompany.py knowledge preflight \
  --tag authority \
  --file scripts/gate.py \
  --risk HIGH
```

Preview candidate promotion with deterministic validation evidence:

```bash
python onecompany.py knowledge promote \
  --id K-EXAMPLE-001 \
  --method regression_test \
  --evidence repo:.onecompany/selftest/test_example.py \
  --validated-at 2026-09-16T00:00:00Z
```

Add `--write` only when the repo change itself is intended. Promotion changes knowledge lifecycle state only; it never changes CompanyOS authority.

## Authority boundary

Every manifest/entry/preflight is `advisory_only` with `authority_effects: []`.

Knowledge can suggest checks, analogous paths and regressions. It cannot mint/transfer leases, satisfy CI/review/Code Owner gates, grant merge authority, expand credentials/budget/autonomy, override live GitHub or Team Room truth, or weaken emergency stop/human-only decisions.

No lesson can invent a new hard gate. A deterministic reviewed policy may independently create a hard gate; knowledge may only remind a worker that the gate exists.

## Lifecycle

A candidate requires provenance but remains unvalidated. Promotion is explicit and requires evidence from a supported validation class: regression test, deterministic reproduction, independent review or repeated evidence. There is no automatic promotion path.

Structurally identical candidates can be deduplicated while preserving every source record and observation count. Claims about the same problem that recommend different prevention rules remain separate conflicts; deterministic reproduction/live facts should resolve them later.

Archived lessons retain audit history and are not injected by default.

## Planning integration

`python onecompany.py plan parallel` and `plan explain <WU>` automatically attach a bounded learning preflight to consequential Work Units. Retrieval is relevance-ranked and capped at eight lessons. The preflight includes reusable checks/regression expectations but always reports `hard_gate_created: false`.

## Fresh installations

Bootstrap never carries project-specific learning history into a new company. Candidate and archived entries are removed. Current entries survive only when explicitly marked `bootstrap_safe: true`, remain advisory-only, and use generic `repo:` or `fixture:` source references rather than project-specific review URLs/commits/identities.

## Privacy

The learning contract rejects secret-like values and sensitive provenance fields. Do not store credentials, private prompts, raw tool transcripts, hidden reasoning, unrestricted local filesystem paths or authentication-bearing URLs.

## Initial reusable lessons

The first generic lessons capture defects repeatedly encountered while hardening CompanyOS:

- bind consequential evidence to exact current state;
- preserve caller failure contracts across lower-layer hardening;
- revalidate mutable filesystem identity at publication boundaries and race the boundary in tests.

Project-specific evidence remains separate from these generic bootstrap-safe lessons.
