from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger_lib

BASE = "b" * 40
OLD = "a" * 40
HEAD = "c" * 40
MERGE = "d" * 40


def event(index: int, kind: str, actor: str, payload: dict, *, version: int = 2) -> dict:
    return {
        "version": version,
        "event_id": f"e{index}",
        "type": kind,
        "actor": actor,
        "payload": payload,
        "github_created_at": f"2026-01-01T00:00:{index:02d}Z",
        "github_comment_id": index,
    }


def planning(dependencies=None) -> dict:
    dependencies = list(dependencies or [])
    return {
        "write_scope": ["src/a/**"],
        "resource_locks": [],
        "parallelism": "auto",
        "risk_class": "LOW",
        "dependencies": dependencies,
        "dependency_closure": dependencies,
    }


def admission(dependencies=None) -> dict:
    dependencies = list(dependencies or [])
    return {
        "schema": ledger_lib.ADMISSION_SCHEMA,
        "actor": "worker",
        "actor_eligible": True,
        "actor_ineligibility_reasons": [],
        "actor_limit": 1,
        "dependencies": dependencies,
        "dependencies_complete": True,
        "transfer_source_lease_id": None,
        "dependencies_inherited_from_source": False,
        "trusted_ref": BASE,
        "policy_blobs": {key: f"blob-{key}" for key in ledger_lib.TRUSTED_POLICY_PATHS},
    }


def trusted_context(dependencies=None) -> dict:
    snap = planning(dependencies)
    return {
        "trusted_ref": BASE,
        "policy_blobs": {key: f"blob-{key}" for key in ledger_lib.TRUSTED_POLICY_PATHS},
        "planning": {
            "parallel_execution": {
                "enabled": True,
                "max_concurrent_implementation_streams": 3,
                "require_write_scope_for_parallel": True,
                "critical_risk_default": "serialize",
            }
        },
        "work_map": {"WU-A": {"id": "WU-A"}},
        "work_item": {"id": "WU-A"},
        "planning_snapshot": snap,
        "actor_limit": 1,
        "actor_eligible": True,
        "actor_ineligibility_reasons": [],
    }


class LedgerPlatformProvenanceTests(unittest.TestCase):
    def test_stale_default_branch_ancestor_cannot_replace_exact_pr_base(self):
        pr_doc = {"base": {"ref": "main", "sha": BASE}}
        with (
            patch.object(ledger_lib, "_repository", return_value="owner/repo"),
            patch.object(ledger_lib, "_pull_request", return_value=pr_doc),
            patch.object(ledger_lib, "_default_branch_tip", return_value=("main", "f" * 40)),
            patch.object(ledger_lib, "_trusted_policy_snapshot") as policies,
        ):
            context, error = ledger_lib.trusted_admission_context(
                OLD, "worker", "WU-A", [], pr=7, cache={}
            )
        self.assertIsNone(context)
        self.assertIn("does not match GitHub PR #7 base", error or "")
        policies.assert_not_called()

    def test_unverified_merged_claim_cannot_unlock_dependency(self):
        merged = event(
            1,
            "MERGED",
            "human-owner",
            {"pr": 6, "work_unit": "WU-B", "merge_sha": MERGE},
        )
        claim = event(
            2,
            "ROLE_LEASE_ASSIGNED",
            "worker",
            {
                "lease_id": "L-A",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 7,
                "planning_snapshot": planning(["WU-B"]),
                "admission_snapshot": admission(["WU-B"]),
            },
        )
        with (
            patch.object(
                ledger_lib,
                "_verify_merged_event",
                return_value=(None, "GitHub PR #6 is not merged"),
            ),
            patch.object(
                ledger_lib,
                "trusted_admission_context",
                return_value=(trusted_context(["WU-B"]), None),
            ),
        ):
            result = ledger_lib.derive(
                [merged, claim],
                enforce_actor_policy=False,
                verify_admission_provenance=True,
            )
        self.assertEqual(result["active_leases"], [])
        self.assertEqual(result["verified_merged_work_units"], [])
        self.assertTrue(
            any(item["reason"] == "invalid_merged_evidence" for item in result["integrity_conflicts"])
        )
        reasons = {
            item["reason"]
            for rejected in result["rejected_claims"]
            for item in rejected.get("violations", [])
        }
        self.assertIn("dependency_not_durably_complete_at_admission", reasons)

    def test_platform_verified_merge_unlocks_dependency_only_after_event_order(self):
        claim_before = event(
            1,
            "ROLE_LEASE_ASSIGNED",
            "worker",
            {
                "lease_id": "EARLY",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 7,
                "planning_snapshot": planning(["WU-B"]),
                "admission_snapshot": admission(["WU-B"]),
            },
        )
        merged = event(
            2,
            "MERGED",
            "human-owner",
            {"pr": 6, "work_unit": "WU-B", "merge_sha": MERGE},
        )
        claim_after = event(
            3,
            "ROLE_LEASE_ASSIGNED",
            "worker",
            {
                "lease_id": "LATE",
                "role": "implementation",
                "work_unit": "WU-A",
                "pr": 7,
                "planning_snapshot": planning(["WU-B"]),
                "admission_snapshot": admission(["WU-B"]),
            },
        )
        verified = {
            "pr": 6,
            "work_unit": "WU-B",
            "approved_base": BASE,
            "approved_head": HEAD,
            "merge_sha": MERGE,
        }
        with (
            patch.object(ledger_lib, "_verify_merged_event", return_value=(verified, None)),
            patch.object(
                ledger_lib,
                "trusted_admission_context",
                return_value=(trusted_context(["WU-B"]), None),
            ),
        ):
            result = ledger_lib.derive(
                [claim_before, merged, claim_after],
                enforce_actor_policy=False,
                verify_admission_provenance=True,
            )
        self.assertEqual([item["id"] for item in result["active_leases"]], ["LATE"])
        self.assertEqual(result["verified_merged_work_units"], ["WU-B"])
        early = next(item for item in result["rejected_claims"] if item["rejected_lease_id"] == "EARLY")
        self.assertIn(
            "dependency_not_durably_complete_at_admission",
            {item["reason"] for item in early["violations"]},
        )

    def test_verified_merge_helper_binds_platform_merge_and_work_unit_mapping(self):
        pr_doc = {
            "merged_at": "2026-01-02T00:00:00Z",
            "merge_commit_sha": MERGE,
            "base": {"ref": "main", "sha": BASE},
            "head": {"sha": HEAD},
        }
        queue = {"work_units": [{"id": "WU-B", "pr": 6}]}
        merged = event(
            1,
            "MERGED",
            "human-owner",
            {
                "pr": 6,
                "work_unit": "WU-B",
                "approved_base": BASE,
                "approved_head": HEAD,
                "merge_sha": MERGE,
            },
        )
        with (
            patch.object(ledger_lib, "_repository", return_value="owner/repo"),
            patch.object(ledger_lib, "_pull_request", return_value=pr_doc),
            patch.object(ledger_lib, "_default_branch_tip", return_value=("main", MERGE)),
            patch.object(ledger_lib, "_assert_trusted_default_branch_history"),
            patch.object(
                ledger_lib,
                "_trusted_json_at_ref",
                return_value=(queue, "queue-blob"),
            ),
        ):
            context, error = ledger_lib._verify_merged_event(merged, {})
        self.assertIsNone(error)
        self.assertEqual(context["work_unit"], "WU-B")
        self.assertEqual(context["approved_base"], BASE)
        self.assertEqual(context["approved_head"], HEAD)
        self.assertEqual(context["merge_sha"], MERGE)

    def test_policy_snapshot_reads_each_protected_blob_once_per_replay_cache(self):
        docs = {
            "queue": {"work_units": []},
            "planning": {},
            "actors": {"actors": []},
            "readiness": {"actors": []},
            "budget": {},
        }

        def read(_repo, path, _ref, _cache):
            key = next(key for key, expected in ledger_lib.TRUSTED_POLICY_PATHS.items() if expected == path)
            return docs[key], f"blob-{key}"

        cache = {}
        with (
            patch.object(ledger_lib, "_assert_trusted_default_branch_history"),
            patch.object(ledger_lib, "_trusted_json_at_ref", side_effect=read) as reads,
        ):
            first = ledger_lib._trusted_policy_snapshot("owner/repo", BASE, cache)
            second = ledger_lib._trusted_policy_snapshot("owner/repo", BASE, cache)
        self.assertIs(first, second)
        self.assertEqual(reads.call_count, len(ledger_lib.TRUSTED_POLICY_PATHS))


if __name__ == "__main__":
    unittest.main()
