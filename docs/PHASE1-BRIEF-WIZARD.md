# Start here — guided Create or Adopt

From a OneCompany **source checkout**, start without needing to learn Work Units,
leases or agent commands:

```bash
python onecompany.py start --target /tmp/my-new-product --repository YOUR_NAME/my-new-product
# Or point --target to an existing local repository to Adopt it.
```

The wizard reports whether the target is **Create** or **Adopt**, and for
an existing project displays detected stack, tests and CI before asking the
**owner** the canonical Product Brief questions: audience, problem, outcome,
smallest first feature, constraints. Missing answers are never guessed.
Discovery blockers halt prompting. The default command creates **no file**,
never calls `--apply`, and never starts a model, Work Unit or deployment.

When ready, explicitly save a new private, **unapproved** draft:

```bash
python onecompany.py start --target /tmp/my-new-product \
  --repository YOUR_NAME/my-new-product --save-to /tmp/my-first-brief.json

python onecompany.py journey --target /tmp/my-new-product \
  --repository YOUR_NAME/my-new-product --brief /tmp/my-first-brief.json
```

A complete draft can be saved only to a **new** regular path through the
existing POSIX secure exporter: mode 0600, exclusive creation, non-symlink
traversal; it refuses an existing file or interrupted/missing required input.
Never use this demo for customer personal data or credentials. The saved JSON
is just an owner-answer-and-discovery **DRAFT_NOT_APPROVED**, not a signed
approval or authority. Save does not overwrite existing product files,
initialize a repo, grant a lease/RunKey, pay a model, merge a PR or deploy.

Source-checkout-only wizard absence in an installed target causes a clear
refusal. Phase-1 end-to-end #153 still requires independently verified
canonical Work Unit authorization, current SHA CI and nonauthor review,
real local app/quality/browser evidence before claiming autonomous delivery.
Phase-2 KServe, OpenViking, Supermemory and ARTEMIS remain planned.
