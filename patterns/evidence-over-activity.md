# Pattern: Evidence Over Activity

## Problem

Autonomous workers can acknowledge assignments, post heartbeats, or say they are “working” while producing no repository change or decision artifact. Treating that as progress hides idle/dead workers.

## Pattern

Progress is evidenced by durable, inspectable artifacts such as:

- commit or branch movement;
- PR update;
- CI/check run;
- review artifact tied to an exact SHA;
- test/diagnostic result;
- issue/work-unit state transition;
- bounded risk/test/design artifact;
- merge/release/deployment evidence.

A heartbeat is telemetry only.

## No-idle implication

If dependency-ready work exists and no valid implementation lease has durable evidence of forward movement, the orchestrator should reconcile rather than assume the worker is active.

## Avoid false pressure

Do not turn this into “every worker must produce something.” Reviewer independence, scope discipline, and avoiding duplicate streams outrank utilization. Evidence-over-activity detects fake progress; it does not mandate busywork.
