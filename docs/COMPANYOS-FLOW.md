# How CompanyOS Works

OneCompany is a governed autonomous-company runtime. The diagram below is the canonical high-level operating view of the system.

```mermaid
flowchart TB
    H[Human Governance & Boundaries\nmission • budget • autonomy • credentials • human-only decisions • risk acceptance]

    subgraph O[Onboarding]
      O1[New repo or existing repo]
      O2[Inspect stack / CI / tests / docs]
      O3[Show adoption plan + collisions]
      O4[Apply safely]
      O1 --> O2 --> O3 --> O4
    end

    subgraph C[CompanyOS Control Plane - .onecompany]
      C1[config / governance / budget]
      C2[actors / readiness / routing / dispatch]
      C3[portfolio / requirements / acceptance criteria / risks]
      C4[queue / leases / state / supervision]
      C5[schemas / assurance / policies]
    end

    subgraph G[GitHub Collaboration & Live Delivery]
      G1[Issues / Projects\nhuman collaboration UI]
      G2[Branches / PRs]
      G3[Commits / exact head SHA]
      G4[Actions / CI]
      G5[Reviews / comments]
      G6[Merges / releases]
    end

    subgraph P[Planning & Flow Engine]
      P1[Objective] --> P2[Epic]
      P2 --> P3[Feature / Capability\noptional]
      P3 --> P4[User Story\noptional]
      P4 --> P5[Formal Requirements]
      P5 --> P6[Acceptance Criteria]
      P6 --> P7[Work Units]
      P8[Priority + critical path + dependency graph]
      P9[Write scope + resource locks + WIP + safe parallel set]
    end

    subgraph R[Capability Router]
      R1[Match capability]
      R2[Check budget]
      R3[Check readiness]
      R4[Check actor capacity]
      R5[Avoid authorship conflicts]
    end

    subgraph W[Workers / Actors]
      W1[ChatGPT]
      W2[Codex]
      W3[Claude]
      W4[GitHub Copilot]
      W5[Gemini]
      W6[Mistral]
      W7[Local agents]
    end

    subgraph X[Parallel Execution Streams]
      XA[WU-A\nlease → branch/PR → CI → review]
      XB[WU-B\nlease → branch/PR → CI → review]
      XC[WU-C\nheld: dependency / scope / lock / capacity conflict]
    end

    subgraph Q[Engineering Assurance]
      Q1[Requirements quality + traceability]
      Q2[Architecture + code quality]
      Q3[Unit / integration / contract / E2E]
      Q4[Security / accessibility / performance / reliability]
      Q5[Coverage / mutation / documentation / evidence]
    end

    subgraph M[Independent Gate & Merge]
      M1[Exact head SHA]
      M2[Exact base SHA]
      M3[Live diff matches declared scope]
      M4[Independent non-author review]
      M5[Required checks green]
      M6[Expected-head merge]
    end

    subgraph L[Release & Learning Loop]
      L1[Release]
      L2[Observability]
      L3[Outcomes + metrics]
      L4[Incidents / escaped defects]
      L5[Retrospective]
      L6[Update requirements / risks / tests / policies]
      L1 --> L2 --> L3 --> L4 --> L5 --> L6
    end

    H --> O
    H --> C
    H --> G
    O --> C
    C <--> G
    C --> P
    G --> P
    P --> R
    R --> W
    W --> X
    P --> X
    X --> Q
    Q --> M
    M --> G6
    G6 --> L1
    L6 --> P

    classDef guard fill:#eef6ff,stroke:#2563eb,stroke-width:2px;
    classDef safe fill:#ecfdf5,stroke:#059669,stroke-width:2px;
    classDef blocked fill:#fff1f2,stroke:#e11d48,stroke-width:2px;
    class H,M1,M2,M3,M4,M5,M6 guard;
    class XA,XB,G6,L1 safe;
    class XC blocked;
```

## Core invariants

- GitHub live state is authoritative for branches, PRs, exact SHAs, CI, reviews and merges.
- Versioned `.onecompany` files are authoritative for approved planning intent and policy.
- Exactly one canonical writer/implementation stream exists **per Work Unit**.
- Multiple WUs may execute concurrently only when dependencies, write scopes, semantic locks, risk, WIP and actor capacity prove them independent.
- A merge-ready gate is bound to the exact candidate head **and** exact base SHA; base movement stales integration evidence.
- Live PR changes must remain inside the WU's declared write scope.
- Failover changes the worker, not the canonical WU stream or its authorship history.
- Material authors may not be the sole independent final reviewer.
- Budget exhaustion or provider quota does not create authority to spend.
- Human sovereignty remains explicit for credentials, budget policy, legal/governance decisions, destructive production actions and critical risk acceptance.
- Release outcomes feed back into requirements, risks, tests, policies and future planning.

See also [`ARCHITECTURE.md`](ARCHITECTURE.md), [`ONBOARDING.md`](ONBOARDING.md), and the engineering standards under [`engineering/`](engineering/).
