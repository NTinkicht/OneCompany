# OneCompany design principles and provenance boundaries

OneCompany's current design is a synthesis of general software engineering,
distributed-systems and human-governance patterns. Historical implementation
experience is preserved in Git history; the **distributed product** contains
only product-independent contracts and sanitised illustrative fixtures.

## Aligned autonomy

A bounded delivery stream owns one Work Unit, lease and canonical PR;
independent specialist review supplies cross-cutting discipline. Automation
cannot silently increase its own autonomy, budget or credentials. Distinct
human and machine permissions are explicit.

## Durable state and coordination

Live source-of-truth evidence outranks cached progress and chat context.
A single implementation lease prevents duplicate writers while unrelated
Work Units may progress in parallel. Agent failover transfers a stream, not
the branch, history or accumulated material authorship.

## Assurance and safety

Deterministic CI and independent review are bound to the same exact head.
A reviewer cannot satisfy independent approval for material code they
authored. Spending is checked before execution; absent permission, unknown
provider billing, stale state, emergency stop or unverified deployment
writers fail closed.

## Optional specialist tools

Role overlays refine questions, never create actor identities or authority.
Optional context compression runs shadow-first and cannot replace the
underlying evidence for security, release or merge decisions. Pin
behaviour-bearing dependencies and review their upgrades.

## Product-independent deployments

The reusable templates, schemas, CLI and policies contain no concrete
customer/product domain, service IDs, endpoint or migration snapshot.
Each installed project derives its own operating authority and evidence
from its current environment. Historical real-project observations may
inspire **sanitised rules** but never form a default installed state.
See [Product independence](PRODUCT-INDEPENDENCE.md) and
[Operating lessons](OPERATING-LESSONS.md).
