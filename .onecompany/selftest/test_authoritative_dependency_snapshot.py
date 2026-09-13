from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lease


class AuthoritativeDependencySnapshotTests(unittest.TestCase):
    def test_full_graph_overrides_stale_declared_dependency_closure(self):
        work_map = {
            "WU-A": {
                "id": "WU-A",
                "dependencies": ["WU-B"],
                "dependency_closure": ["WU-B"],
                "write_scope": ["src/a/**"],
                "resource_locks": [],
                "parallelism": "auto",
                "risk_class": "LOW",
            },
            "WU-B": {"id": "WU-B", "dependencies": ["WU-C"]},
            "WU-C": {"id": "WU-C", "dependencies": []},
        }
        snapshot = lease.planning_snapshot(work_map["WU-A"], work_map)
        self.assertEqual(snapshot["dependencies"], ["WU-B"])
        self.assertEqual(snapshot["dependency_closure"], ["WU-B", "WU-C"])


if __name__ == "__main__":
    unittest.main()
