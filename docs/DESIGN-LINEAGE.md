# OneCompany Design Lineage

OneCompany is a synthesis of techniques that were exercised while operating Tabibi plus ideas deliberately adapted from external engineering work. This document separates **what was actually used**, **what was adapted**, and **what is merely related evidence** so the project does not invent a false origin story.

## 1. Tabibi: the proving ground

The reference operating experience came from `NTinkicht/Tabibi`.

Two key Epic slices made the model concrete:

- PR #151 — zero-extra-cost context router and AI capacity governor;
- PR #158 — six-actor Company OS with deterministic capability routing and Spotify-inspired organization.

Tabibi exposed practical failures that shaped OneCompany: quota exhaustion, stale state, duplicate-work risk, stale exact-SHA reviews, worker wake/runtime failures, context waste, formatting remediation by guess instead of running the formatter, and agents appearing active without durable output.

OneCompany turns those lessons into generic invariants rather than copying Tabibi's healthcare/product details.

## 2. Spotify engineering culture → aligned autonomy

### Source

Spotify Engineering published its engineering-culture material in 2014 describing autonomous squads plus chapters/guilds. Spotify itself described the material as a journey in progress, not a universal framework.

### What Tabibi adapted

The Epic restructuring used:

- temporary bounded **squads** around one delivery stream;
- **chapters** as reusable discipline standards;
- **guilds** as lightweight cross-cutting specialist overlays;
- autonomy constrained by alignment and company-wide invariants.

### What OneCompany keeps

OneCompany keeps aligned autonomy and the three useful structural ideas, but makes them machine/agent-friendly:

- a squad maps to a Work Unit + leases + canonical PR;
- a chapter maps to executable standards/contracts/tests;
- a guild maps to optional advisory specialist lanes/overlays.

It intentionally avoids literal organizational copying or mandatory ceremony.

See `patterns/spotify-aligned-autonomy.md`.

## 3. Agency Agents → role overlays, not fake employees

### Source used in Tabibi

Tabibi curated specialist profiles from the fork `NTinkicht/agency-agents`, pinned at commit:

`647c8baa42b6842afb4a97bf2c0950d45ba88e8b`

That fork's source lineage is `msitarzewski/agency-agents` and it is MIT licensed at the pinned revision.

### Important adaptation

OneCompany does **not** equate a specialist prompt/persona with an independent worker.

An actor is a model/tool identity with real capacity, permissions, authorship and review eligibility. A role overlay is only a professional lens for one bounded task.

Therefore an overlay cannot:

- create capacity;
- create a lease;
- grant write permission;
- erase material authorship;
- make self-review independent;
- create merge authority.

This distinction was one of the most important governance improvements made in Tabibi.

See `overlays/` and `patterns/role-overlays.md`.

## 4. Headroom → local context compression + shadow adoption

### Source used in Tabibi

Tabibi evaluated `NTinkicht/headroom` pinned at:

`97aa9f6d0fc04619e4e821e7d54611eb9d6b9b81`

The fork was synchronized through upstream `headroomlabs-ai/headroom` commit:

`04cdf79ab0a8423d88148ba63e960ac6b4007b9c`

### What mattered more than the tool

The durable technique was **shadow before authority**:

- run experimental context compression locally/read-only beside the authoritative path;
- keep original evidence authoritative;
- exclude secrets/sensitive data;
- pin and verify provenance;
- measure omissions as well as compression ratio;
- graduate only after project-specific fidelity evidence.

This became a generic OneCompany adoption pattern for routers, agents, reviewers, summarizers, and model upgrades.

See `patterns/shadow-before-authority.md` and `patterns/context-ladder.md`.

## 5. Tabibi-native synthesis

The following patterns emerged from operating the system rather than from a single external framework:

- **single-stream lease** — one canonical implementation writer/stream per bounded WU;
- **orthogonal parallelism** — spare workers create non-conflicting artifacts rather than duplicate code;
- **exact-head two-key gate** — deterministic CI + independent non-author review on the same SHA;
- **capacity circuit breaker** — quota exhaustion is degraded capacity, not permission to spend;
- **evidence over activity** — durable artifacts outrank heartbeats/acknowledgements;
- **GitHub truth / local cache** — derived state is convenient but live repository state wins;
- **expected-head merge** — mechanically refuse to merge a head different from the approved one;
- **failover keeps the stream** — change the worker, not the branch/PR/objective/history.

These are the core of OneCompany because they solved repeated real coordination failures.

## 6. Related modern evidence — useful, but not the origin

Spotify's later **Honk** background-coding-agent series (2025–2026) independently reinforces several OneCompany choices: pluggable agents behind surrounding infrastructure, context engineering, verification loops, constrained agent permissions, CI as an outer loop, traceability, and outcome-based accountability.

Those posts were not the origin of Tabibi's earlier design decisions documented above; they are useful convergent evidence and future research input.

## 7. What OneCompany deliberately excludes

Not every successful Tabibi mechanism belongs in a universal starter repo. OneCompany does not bake in:

- Tabibi healthcare/domain rules;
- named-provider role assignments;
- Slack/coffee-corner culture details;
- project-specific queue/database/realtime techniques;
- paid-service assumptions;
- a requirement to own six AI subscriptions.

The rule is: **extract the invariant, not the accident of one project.**
