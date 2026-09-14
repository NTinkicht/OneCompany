from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from planning_lib import implementation_admission_violations


class AuthoritativeDependencyAdmissionTests(unittest.TestCase):
    def test_authoritative_queue_item_recomputes_stale_dependency_closure_before_admission(self):
        work = [
            {
                "id": "WU-A",
                "dependencies": ["WU-B"],
                "dependency_closure": ["WU-B"],  # stale/incomplete cache
                "parallelism": "auto",
                "risk_class": "LOW",
                "write_scope": ["src/a/**"],
                "resource_locks": [],
            },
            {
                "id": "WU-B",
                "dependencies": ["WU-C"],
                "parallelism": "auto",
                "risk_class": "LOW",
                "write_scope": ["src/b/**"],
                "resource_locks": [],
            },
            {
                "id": "WU-C",
                "dependencies": [],
                "parallelism": "auto",
                "risk_class": "LOW",
                "write_scope": ["src/c/**"],
                "resource_locks": [],
            },
        ]
        work_map = {item["id"]: item for item in work}
        active_c = {
            "id": "LEASE-C",
            "role": "implementation",
            "actor": "codex",
            "work_unit": "WU-C",
            "planning_snapshot": {
                "dependencies": [],
                "dependency_closure": [],
                "parallelism": "auto",
                "risk_class": "LOW",
                "write_scope": ["src/c/**"],
                "resource_locks": [],
            },
        }
        planning = {
            "parallel_execution": {
                "enabled": True,
                "max_concurrent_implementation_streams": 3,
                "require_write_scope_for_parallel": True,
                "critical_risk_default": "serialize",
            }
        }

        violations = implementation_admission_violations(
            work_map["WU-A"],
            [active_c],
            planning,
            work_map,
            actor="claude",
            actor_limit=2,
        )

        details = {
            detail
            for violation in violations
            for detail in violation.get("details", [])
        }
        self.assertIn("dependency_relationship", details)


if __name__ == "__main__":
    unittest.main()
