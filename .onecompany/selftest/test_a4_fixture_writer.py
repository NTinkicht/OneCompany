from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fixture_actions_adapter as worker
import dispatch_execute_entry


REPO = "example/disposable"
HEAD = "a" * 40
BASE = "b" * 40
PATH = "docs/onecompany-fixture/WU-A.md"


def fixture() -> tuple[dict, dict, dict, dict]:
    req = {
        "repository": REPO,
        "work_unit": "WU-A",
        "actor": "fixture-actor",
        "capability": "implementation",
        "unattended": True,
        "lease": {
            "id": "lease-synthetic",
            "role": "implementation",
            "work_unit": "WU-A",
            "actor": "fixture-actor",
            "branch": "wu-a",
            "pr": 12,
            "start_head": HEAD,
            "planning_snapshot": {
                "risk_class": "LOW",
                "write_scope": [PATH],
            },
            "admission_snapshot": {"trusted_ref": BASE},
        },
    }
    config = {
        "autonomy": {"level": "L2"},
        "project": {"repository": REPO, "default_branch": "main"},
        "safety": {"emergency_stop": False},
    }
    queue = {
        "work_units": [
            {"id": "WU-A", "branch": "wu-a", "pr": 12, "status": "READY"}
        ]
    }
    pr = {
        "number": 12,
        "state": "open",
        "draft": False,
        "head": {"sha": HEAD, "ref": "wu-a",
                 "repo": {"full_name": REPO}},
        "base": {"sha": BASE, "ref": "main",
                 "repo": {"full_name": REPO}},
    }
    return req, config, queue, pr


def check(req: dict, cfg: dict, q: dict, pr: dict) -> list[str]:
    return worker.preflight(
        req, cfg, q, pr, repository=REPO, actions=True, enabled=True
    )


class A4FixtureWorkerTests(unittest.TestCase):
    def test_admission_succeeds_only_for_bound_synthetic_low_risk_pr(self) -> None:
        self.assertEqual(check(*fixture()), [])

    def test_unattended_l1_rejected_before_external_write(self) -> None:
        request, cfg, q, pr = fixture()
        cfg["autonomy"]["level"] = "L1"
        self.assertIn(
            "unattended_implementation_requires_approved_L2",
            check(request, cfg, q, pr),
        )
        with (
            patch.dict(
                worker.os.environ,
                {
                    "GITHUB_REPOSITORY": REPO,
                    "GITHUB_ACTIONS": "true",
                    "ONECOMPANY_A4_FIXTURE_ENABLED": "true",
                },
            ),
            patch.object(worker, "load_json", side_effect=[cfg, q]),
            patch.object(worker, "_live_pr", return_value=pr),
            patch.object(worker, "_cmd") as shell,
        ):
            with self.assertRaisesRegex(RuntimeError, "requires_approved_L2"):
                worker.invoke(request)
            shell.assert_not_called()

    def test_missing_opt_in_or_trusted_runtime_rejected(self) -> None:
        req, cfg, q, pr = fixture()
        self.assertIn(
            "fixture_worker_not_owner_enabled",
            worker.preflight(req, cfg, q, pr, repository=REPO,
                             actions=True, enabled=False),
        )
        self.assertIn(
            "github_actions_runtime_required",
            worker.preflight(req, cfg, q, pr, repository=REPO,
                             actions=False, enabled=True),
        )

    def test_wrong_repo_and_forked_pr_rejected(self) -> None:
        req, cfg, q, pr = fixture()
        self.assertIn(
            "repository_identity_mismatch",
            worker.preflight(req, cfg, q, pr, repository="foreign/repo",
                             actions=True, enabled=True),
        )
        pr["head"]["repo"]["full_name"] = "foreign/fork"
        self.assertIn("canonical_pr_head_changed_or_foreign", check(req, cfg, q, pr))

    def test_stale_base_or_head_rejected(self) -> None:
        req, cfg, q, pr = fixture()
        pr["head"]["sha"] = "c" * 40
        self.assertIn("canonical_pr_head_changed_or_foreign", check(req, cfg, q, pr))
        pr["head"]["sha"] = HEAD
        pr["base"]["sha"] = "d" * 40
        self.assertIn("canonical_pr_base_changed_or_foreign", check(req, cfg, q, pr))

    def test_queue_rebinding_or_high_risk_rejected(self) -> None:
        req, cfg, q, pr = fixture()
        q["work_units"][0]["pr"] = 19
        self.assertIn("protected_queue_stream_binding_mismatch", check(req, cfg, q, pr))
        q["work_units"][0]["pr"] = 12
        req["lease"]["planning_snapshot"]["risk_class"] = "MEDIUM"
        self.assertIn("test_only_low_risk_work_unit_required", check(req, cfg, q, pr))
        req["lease"]["planning_snapshot"]["risk_class"] = "LOW"
        req["lease"]["planning_snapshot"]["write_scope"] = ["**/*"]
        self.assertIn("test_only_exact_fixture_write_scope_required", check(req, cfg, q, pr))

    def test_missing_trusted_base_and_stop_fail_closed(self) -> None:
        req, cfg, q, pr = fixture()
        req["lease"]["admission_snapshot"].pop("trusted_ref")
        self.assertIn("protected_base_evidence_missing", check(req, cfg, q, pr))
        cfg["safety"]["emergency_stop"] = True
        self.assertIn("emergency_stop_or_unknown", check(req, cfg, q, pr))

    def test_path_traversal_or_shell_identity_is_not_accepted(self) -> None:
        for value in ("../outside", "WU/../../X", "WU-hello world", "WU;touch /tmp/X"):
            self.assertIsNone(worker.fixture_path(value))

    def test_adapter_is_registered_but_not_enabled_by_source_defaults(self) -> None:
        self.assertIs(
            dispatch_execute_entry.ADAPTERS[worker.MECHANISM_ID],
            worker.invoke,
        )


if __name__ == "__main__":
    unittest.main()
