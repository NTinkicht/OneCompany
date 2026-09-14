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


def merged_event(index: int, pr: int, work_unit: str, *, base: str, head: str, merge: str) -> dict:
    return event(
        index,
        "MERGED",
        "human-owner",
        {
            "pr": pr,
            "work_unit": work_unit,
            "approved_base": base,
            "approved_head": head,
            "merge_sha": merge,
        },
    )


def merged_pr_doc(*, base: str, head: str, merge: str) -> dict:
    return {
        "merged_at": "2026-01-02T00:00:00Z",
        "merge_commit_sha": merge,
        "base": {"ref": "main", "sha": base},
        "head": {"sha": head},
    }


class LedgerPlatformProvenanceTests(unittest.TestCase):
    def tearDown(self):
        ledger_lib.clear_verified_merge_cache()

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

    def test_successive_derive_replays_do_not_reverify_unchanged_merged_history(self):
        base1, head1, merge1 = "1" * 40, "2" * 40, "3" * 40
        base2, head2, merge2 = "4" * 40, "5" * 40, "6" * 40
        events = [
            merged_event(1, 11, "WU-11", base=base1, head=head1, merge=merge1),
            merged_event(2, 12, "WU-12", base=base2, head=head2, merge=merge2),
        ]
        pr_docs = {
            11: merged_pr_doc(base=base1, head=head1, merge=merge1),
            12: merged_pr_doc(base=base2, head=head2, merge=merge2),
        }
        queues = {
            base1: {"work_units": [{"id": "WU-11", "pr": 11}]},
            base2: {"work_units": [{"id": "WU-12", "pr": 12}]},
        }

        def read_pr(_repo, pr, _cache):
            return pr_docs[pr]

        def read_json(_repo, _path, ref, _cache):
            return queues[ref], f"queue-{ref[:4]}"

        ledger_lib.clear_verified_merge_cache()
        with (
            patch.object(ledger_lib, "_repository", return_value="owner/repo"),
            patch.object(ledger_lib, "_pull_request", side_effect=read_pr) as pulls,
            patch.object(ledger_lib, "_default_branch_tip", return_value=("main", "f" * 40)),
            patch.object(ledger_lib, "_assert_trusted_default_branch_history"),
            patch.object(ledger_lib, "_trusted_json_at_ref", side_effect=read_json) as reads,
        ):
            first = ledger_lib.derive(
                events,
                enforce_actor_policy=False,
                verify_admission_provenance=True,
            )
            first_pull_count = pulls.call_count
            first_read_count = reads.call_count
            second = ledger_lib.derive(
                events,
                enforce_actor_policy=False,
                verify_admission_provenance=True,
            )
        self.assertEqual(first["verified_merged_work_units"], ["WU-11", "WU-12"])
        self.assertEqual(second["verified_merged_work_units"], ["WU-11", "WU-12"])
        self.assertEqual(first_pull_count, 2)
        self.assertEqual(first_read_count, 2)
        self.assertEqual(pulls.call_count, first_pull_count)
        self.assertEqual(reads.call_count, first_read_count)

    def test_new_merge_triggers_only_new_verification_after_cached_replay(self):
        base1, head1, merge1 = "1" * 40, "2" * 40, "3" * 40
        base2, head2, merge2 = "4" * 40, "5" * 40, "6" * 40
        first_events = [
            merged_event(1, 11, "WU-11", base=base1, head=head1, merge=merge1),
        ]
        second_events = [
            *first_events,
            merged_event(2, 12, "WU-12", base=base2, head=head2, merge=merge2),
        ]
        pr_docs = {
            11: merged_pr_doc(base=base1, head=head1, merge=merge1),
            12: merged_pr_doc(base=base2, head=head2, merge=merge2),
        }
        queues = {
            base1: {"work_units": [{"id": "WU-11", "pr": 11}]},
            base2: {"work_units": [{"id": "WU-12", "pr": 12}]},
        }

        ledger_lib.clear_verified_merge_cache()
        with (
            patch.object(ledger_lib, "_repository", return_value="owner/repo"),
            patch.object(ledger_lib, "_pull_request", side_effect=lambda _r, p, _c: pr_docs[p]) as pulls,
            patch.object(ledger_lib, "_default_branch_tip", return_value=("main", "f" * 40)),
            patch.object(ledger_lib, "_assert_trusted_default_branch_history"),
            patch.object(
                ledger_lib,
                "_trusted_json_at_ref",
                side_effect=lambda _r, _p, ref, _c: (queues[ref], f"queue-{ref[:4]}"),
            ) as reads,
        ):
            ledger_lib.derive(
                first_events,
                enforce_actor_policy=False,
                verify_admission_provenance=True,
            )
            self.assertEqual(pulls.call_count, 1)
            self.assertEqual(reads.call_count, 1)
            second = ledger_lib.derive(
                second_events,
                enforce_actor_policy=False,
                verify_admission_provenance=True,
            )
        self.assertEqual(second["verified_merged_work_units"], ["WU-11", "WU-12"])
        self.assertEqual(pulls.call_count, 2)
        self.assertEqual(reads.call_count, 2)

    def test_platform_outage_never_caches_unverified_merge_as_authority(self):
        base, head, merge = "1" * 40, "2" * 40, "3" * 40
        events = [merged_event(1, 11, "WU-11", base=base, head=head, merge=merge)]
        ledger_lib.clear_verified_merge_cache()
        with (
            patch.object(ledger_lib, "_repository", return_value="owner/repo"),
            patch.object(ledger_lib, "_pull_request", side_effect=RuntimeError("platform outage")) as pulls,
        ):
            first = ledger_lib.derive(
                events,
                enforce_actor_policy=False,
                verify_admission_provenance=True,
            )
            second = ledger_lib.derive(
                events,
                enforce_actor_policy=False,
                verify_admission_provenance=True,
            )
        self.assertEqual(first["verified_merged_work_units"], [])
        self.assertEqual(second["verified_merged_work_units"], [])
        self.assertEqual(pulls.call_count, 2)
        self.assertTrue(
            all(
                item["reason"] == "invalid_merged_evidence"
                for item in second["integrity_conflicts"]
            )
        )

    def test_verified_merge_cache_isolated_by_repo_pr_and_merge_sha(self):
        base, head, merge = "1" * 40, "2" * 40, "3" * 40
        wrong_merge = "4" * 40
        first_event = merged_event(1, 11, "WU-11", base=base, head=head, merge=merge)
        other_pr_event = merged_event(2, 12, "WU-12", base=base, head=head, merge=merge)
        wrong_merge_event = merged_event(3, 11, "WU-11", base=base, head=head, merge=wrong_merge)
        docs = {
            11: merged_pr_doc(base=base, head=head, merge=merge),
            12: merged_pr_doc(base=base, head=head, merge=merge),
        }
        queue = {"work_units": [{"id": "WU-11", "pr": 11}, {"id": "WU-12", "pr": 12}]}

        ledger_lib.clear_verified_merge_cache()
        with (
            patch.object(ledger_lib, "_repository", return_value="owner/repo") as repository,
            patch.object(ledger_lib, "_pull_request", side_effect=lambda _r, p, _c: docs[p]) as pulls,
            patch.object(ledger_lib, "_default_branch_tip", return_value=("main", "f" * 40)),
            patch.object(ledger_lib, "_assert_trusted_default_branch_history"),
            patch.object(ledger_lib, "_trusted_json_at_ref", return_value=(queue, "queue-blob")),
        ):
            context, error = ledger_lib._verify_merged_event(first_event, {})
            self.assertIsNone(error)
            self.assertEqual(context["pr"], 11)
            cached_context, cached_error = ledger_lib._verify_merged_event(first_event, {})
            self.assertIsNone(cached_error)
            self.assertEqual(cached_context["pr"], 11)
            self.assertEqual(pulls.call_count, 1)

            other_pr_context, other_pr_error = ledger_lib._verify_merged_event(other_pr_event, {})
            self.assertIsNone(other_pr_error)
            self.assertEqual(other_pr_context["pr"], 12)
            self.assertEqual(pulls.call_count, 2)

            wrong_context, wrong_error = ledger_lib._verify_merged_event(wrong_merge_event, {})
            self.assertIsNone(wrong_context)
            self.assertIn("does not match GitHub PR #11", wrong_error or "")
            self.assertEqual(pulls.call_count, 3)

            repository.return_value = "other/repo"
            repo_context, repo_error = ledger_lib._verify_merged_event(first_event, {})
            self.assertIsNone(repo_error)
            self.assertEqual(repo_context["pr"], 11)
            self.assertEqual(pulls.call_count, 4)


if __name__ == "__main__":
    unittest.main()
