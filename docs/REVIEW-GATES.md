# Review and Merge Gates

## Two independent questions

Before merge, OneCompany asks:

1. **Does the repository’s deterministic verification pass?**
2. **Does an eligible independent reviewer judge the exact candidate head acceptable against the WU contract and relevant risks?**

Both may be required.

## Exact-head rule

Every final review request states the SHA:

```text
Target exact head: abcdef1234...
```

The reviewer confirms the checked-out/retrieved head matches. If a new commit lands, the previous final verdict becomes stale.

## Independence rule

Default: a material author cannot be the sole independent final reviewer.

Material authorship includes substantive implementation, security-sensitive changes, migrations, test behavior that materially defines correctness, or architectural changes. Purely mechanical actions may be classified differently by project policy, but should not erase earlier authorship.

## Required review scope

A final reviewer should inspect:

- WU objective/non-goals/acceptance criteria;
- full PR diff against base, not only latest commit;
- affected contracts and adjacent unchanged code where risk crosses boundaries;
- test adequacy;
- security/privacy behavior;
- migrations/backward compatibility where applicable;
- exact-head CI state;
- unresolved review threads/findings;
- budget/scope violations if relevant.

## Severity vocabulary

Recommended:

- `BLOCKER` — unsafe/incorrect to merge;
- `MAJOR` — material correctness/security/architecture defect;
- `MEDIUM` — meaningful issue that configured policy may require before merge;
- `MINOR` — polish/local maintainability;
- `NIT` — optional style/preference.

Project policy defines the required resolution threshold. A strong default is all `MEDIUM+` resolved before autonomous merge.

## Verdict vocabulary

Final exact-head verdict should be unambiguous:

- `PASS — MERGE_READY`
- `CHANGES_REQUIRED`
- `BLOCKED — CI_RED`
- `BLOCKED — HUMAN_DECISION`
- `BLOCKED — CAPACITY`

A prose review with no current-SHA final verdict is useful feedback but not a merge gate.

## CI ordering

Prefer obtaining expensive independent final review after deterministic CI is green, but reviewers may start read-only review while CI runs. They must not emit final merge-ready verdict until required checks complete.

## Mechanical changes after review

Do not assume “format-only” or “docs-only” means a previous exact-head approval remains valid. The safest rule is new SHA → refreshed exact-head confirmation. Projects may implement a narrow gate-preserving class only if it is machine-verified and explicitly allowed.

## Merge integrity

Merge executor must:

1. fetch current PR head;
2. compare it with approved exact SHA;
3. verify required CI still green;
4. verify required findings resolved;
5. merge using expected-head protection if API supports it;
6. reconcile issue/WU/state afterwards.

If head differs, stop and re-gate.
