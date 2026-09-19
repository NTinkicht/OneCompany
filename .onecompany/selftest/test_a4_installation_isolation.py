from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fixture_actions_adapter as worker


HEAD = "a" * 40
BASE = "b" * 40


def installation(repository: str, work_unit: str, pr_number: int) -> tuple[dict, dict, dict, dict]:
    branch = work_unit.lower()
    path = f"docs/onecompany-fixture/{work_unit}.md"
    request = {
        "repository": repository,
        "work_unit": work_unit,
        "actor": "fixture-actor",
        "capability": "implementation",
        "unattended": True,
        "lease": {
            "id": f"lease-{work_unit}",
            "role": "implementation",
            "work_unit": work_unit,
            "actor": "fixture-actor",
            "branch": branch,
            "pr": pr_number,
            "start_head": HEAD,
            "planning_snapshot": {"risk_class": "LOW", "write_scope": [path]},
            "admission_snapshot": {"trusted_ref": BASE},
        },
    }
    config = {
        "autonomy": {"level": "L2"},
        "project": {"repository": repository, "default_branch": "main"},
        "safety": {"emergency_stop": False},
    }
    queue = {
        "work_units": [
            {"id": work_unit, "branch": branch, "pr": pr_number, "status": "READY"}
        ]
    }
    pr = {
        "number": pr_number,
        "state": "open",
        "draft": False,
        "head": {"sha": HEAD, "ref": branch, "repo": {"full_name": repository}},
        "base": {"sha": BASE, "ref": "main", "repo": {"full_name": repository}},
    }
    return request, config, queue, pr


class A4InstallationIsolationTests(unittest.TestCase):
    def test_two_distinct_installations_are_independently_admissible(self) -> None:
        first = installation("owner-a/disposable-a", "WU-A", 12)
        second = installation("owner-b/disposable-b", "WU-B", 27)

        for repository, bundle in (
            ("owner-a/disposable-a", first),
            ("owner-b/disposable-b", second),
        ):
            request, config, queue, pr = bundle
            self.assertEqual(
                worker.preflight(
                    request,
                    config,
                    queue,
                    pr,
                    repository=repository,
                    actions=True,
                    enabled=True,
                ),
                [],
            )

    def test_installation_identity_cannot_be_replayed_across_projects(self) -> None:
        first = installation("owner-a/disposable-a", "WU-A", 12)
        second = installation("owner-b/disposable-b", "WU-B", 27)
        request, config, queue, pr = copy.deepcopy(first)
        foreign_repository = second[1]["project"]["repository"]

        errors = worker.preflight(
            request,
            config,
            queue,
            pr,
            repository=foreign_repository,
            actions=True,
            enabled=True,
        )
        self.assertIn("repository_identity_mismatch", errors)

        request["repository"] = foreign_repository
        config["project"]["repository"] = foreign_repository
        errors = worker.preflight(
            request,
            config,
            queue,
            pr,
            repository=foreign_repository,
            actions=True,
            enabled=True,
        )
        self.assertIn("canonical_pr_head_changed_or_foreign", errors)
        self.assertIn("canonical_pr_base_changed_or_foreign", errors)


if __name__ == "__main__":
    unittest.main()
