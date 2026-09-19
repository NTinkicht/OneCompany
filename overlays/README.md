# OneCompany Role Overlays

Role overlays are optional task-specific professional lenses. They sharpen an actor's questions and expected artifact without changing who the actor is.

Machine registry: `.onecompany/overlays.json`.

## Usage

A Work Unit should record:

```text
primary_overlay: backend-architect
specialist_overlays: [database-reliability]
```

The actor still needs the real lease/capability/permission to perform the work.

## Rules

- Prefer zero or one primary overlay; do not build persona stacks for decoration.
- Specialist overlays should be orthogonal.
- A binding reviewer still must be an independent non-author actor.
- An overlay does not grant write or merge permission.
- Overlay findings use the project's canonical severity/verdict system.
- Upstream profile changes are opt-in; never auto-sync behavior into a governed project.

## Provenance

Specialist-profile libraries informed the concept. OneCompany overlays are concise, governance-focused adaptations, not wholesale copies of upstream personalities; see third-party attribution in `docs/REFERENCES.md`.
