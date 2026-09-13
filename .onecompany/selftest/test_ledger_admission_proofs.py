from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger_lib


def event(index: int, kind: str, actor: str, payload: dict, *, version: int) -> dict:
    return {
        "version": version,
        "event_id": f"e{index}",
        "type": kind,
        "actor": actor,
        "payload": payload,
        "github_created_at": f"2026-01-01T00:00:{index:02d}Z",
        "github_comment_id": index,
    }


def planning(scope: str, dependencies=None) -> dict:
    dependencies = dependencies or []
    return {
        "write_scope": [scope],
        "resource_locks": [],
        "parallelism": "auto",
        "risk_class": "LOW",
        "dependencies": list(dependencies),
        "dependency_closure": list(dependencies),
    }


def admission(actor: str, dependencies=None, *, source=None) -> dict:
    return {
        "schema": "onecompany-lease-admission-v1",
        "actor": actor,
        "actor_eligible": True,
        "actor_ineligibility_reasons": [],
        "actor_limit": 1,
        "dependencies": list(dependencies or []),
        # Deliberately forged/descriptive: replay must not trust this boolean.
        "dependencies_complete": True,
        "transfer_source_lease_id": source,
        "dependencies_inherited_from_source": source is not None,
    }


class DurableAdmissionProofTests(unittest.TestCase):
    def test_forged_true_dependency_flag_does_not_replace_merge_evidence(self):
        assignment = event(
            1,
            "ROLE_LEASE_ASSIGNED",
            "codex",
            {
                "lease_id": "L-A",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 2,
                "planning_snapshot": planning("src/a/**", ["WU-B"]),
                "admission_snapshot": admission("codex", ["WU-B"]),
            },
            version=2,
        )
        blocked = ledger_lib.derive([assignment], enforce_actor_policy=False)
        self.assertEqual(blocked["active_leases"], [])
        reasons = {
            item["reason"]
            for claim in blocked["rejected_claims"]
            for item in claim.get("violations", [])
        }
        self.assertIn("dependency_not_durably_complete_at_admission", reasons)

        merged = event(
            1,
            "MERGED",
            "human-owner",
            {"pr": 1, "work_unit": "WU-B", "merge_sha": "m"},
            version=2,
        )
        assignment["event_id"] = "e2"
        assignment["github_comment_id"] = 2
        assignment["github_created_at"] = "2026-01-01T00:00:02Z"
        accepted = ledger_lib.derive([merged, assignment], enforce_actor_policy=False)
        self.assertEqual([item["id"] for item in accepted["active_leases"]], ["L-A"])

    def test_pre_cutoff_v1_replay_keeps_one_slot_actor_arbitration(self):
        first = event(
            1,
            "ROLE_LEASE_ASSIGNED",
            "codex",
            {
                "lease_id": "L1",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 1,
                "planning_snapshot": planning("src/a/**"),
            },
            version=1,
        )
        second = event(
            2,
            "ROLE_LEASE_ASSIGNED",
            "codex",
            {
                "lease_id": "L2",
                "role": "implementation",
                "work_unit": "WU-B",
                "pr": 2,
                "planning_snapshot": planning("src/b/**"),
            },
            version=1,
        )
        frozen_migration = {
            "legacy_v1_actor_limits": {"codex": 1},
            "legacy_v1_unknown_actor_limit": 1,
        }
        with patch.object(ledger_lib, "ledger_config", return_value=frozen_migration):
            result = ledger_lib.derive([first, second], enforce_actor_policy=False)
        self.assertEqual([item["id"] for item in result["active_leases"]], ["L1"])
        reasons = {
            item["reason"]
            for claim in result["rejected_claims"]
            for item in claim.get("violations", [])
        }
        self.assertIn("actor_capacity_exhausted", reasons)

    def test_v2_transfer_binds_source_snapshot_instead_of_new_dependency_claim(self):
        source = event(
            1,
            "ROLE_LEASE_ASSIGNED",
            "codex",
            {
                "lease_id": "L1",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 1,
                "planning_snapshot": planning("src/a/**"),
                "admission_snapshot": admission("codex"),
            },
            version=2,
        )
        transfer = event(
            2,
            "ROLE_LEASE_TRANSFERRED",
            "chatgpt",
            {
                "lease_id": "L2",
                "old_lease_id": "L1",
                "new_lease_id": "L2",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 1,
                "planning_snapshot": planning("src/a/**"),
                "admission_snapshot": admission("chatgpt", source="L1"),
            },
            version=2,
        )
        result = ledger_lib.derive([source, transfer], enforce_actor_policy=False)
        self.assertEqual([item["id"] for item in result["active_leases"]], ["L2"])
        self.assertEqual(result["integrity_conflicts"], [])


if __name__ == "__main__":
    unittest.main()
