"""OC-P0-04: 100+ simulated competing lease claims against the ledger race algebra.

Events are supplied in canonical ledger order (GitHub created_at, then comment id), exactly
as ``ledger_lib.list_events`` returns them; ``derive`` must then admit at most one claimant.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".onecompany" / "selftest"))

from ledger_lib import derive as derive_live  # noqa: E402
from test_ledger_parallelism import snapshot  # noqa: E402

CLAIMANTS = 120
SOURCE_HEAD = "a" * 40
NEXT_HEAD = "b" * 40


def derive(events):
    return derive_live(
        events, None, enforce_actor_policy=False, verify_admission_provenance=False
    )


def event(index: int, kind: str, actor: str, payload: dict) -> dict:
    return {
        "version": 1,
        "event_id": f"e{index}",
        "type": kind,
        "actor": actor,
        "payload": payload,
        "github_created_at": f"2026-01-01T{index // 3600:02d}:{index // 60 % 60:02d}:{index % 60:02d}Z",
        "github_comment_id": index,
    }


def assign(index: int, work_unit: str, scope: str) -> dict:
    return event(
        index,
        "ROLE_LEASE_ASSIGNED",
        f"actor{index}",
        {
            "lease_id": f"L{index}",
            "role": "implementation",
            "work_unit": work_unit,
            "branch": f"wu/{index}",
            "pr": index,
            "planning_snapshot": snapshot(scope),
        },
    )


def reasons(rejected: dict) -> set[str]:
    return {item["reason"] for item in rejected["violations"]}


def details(rejected: dict) -> set[str]:
    return {d for item in rejected["violations"] for d in item.get("details", [])}


class CompetingClaimTests(unittest.TestCase):
    def assert_single_winner(self, result: dict, winner: str, losers: int) -> None:
        self.assertEqual([lease["id"] for lease in result["active_leases"]], [winner])
        self.assertEqual(result["integrity_conflicts"], [])
        self.assertEqual(len(result["rejected_claims"]), losers)
        self.assertNotIn(winner, {c["rejected_lease_id"] for c in result["rejected_claims"]})

    def test_same_work_unit_claims_admit_exactly_the_earliest(self) -> None:
        events = [assign(i, "WU-A", "src/a/**") for i in range(1, CLAIMANTS + 1)]
        result = derive(events)
        self.assert_single_winner(result, "L1", CLAIMANTS - 1)
        for rejected in result["rejected_claims"]:
            self.assertIn("implementation_lease_already_active_for_wu", reasons(rejected))

    def test_overlapping_scope_claims_on_distinct_work_units_admit_one(self) -> None:
        events = [assign(i, f"WU-{i:03d}", "src/shared/**") for i in range(1, CLAIMANTS + 1)]
        result = derive(events)
        self.assert_single_winner(result, "L1", CLAIMANTS - 1)
        for rejected in result["rejected_claims"]:
            self.assertIn("write_scope_overlap", details(rejected))

    def test_competing_transfers_from_one_source_admit_exactly_one_successor(self) -> None:
        base = assign(1, "WU-A", "src/a/**")
        base["payload"]["start_head"] = SOURCE_HEAD
        events = [base]
        for i in range(2, CLAIMANTS + 2):
            events.append(
                event(
                    i,
                    "ROLE_LEASE_TRANSFERRED",
                    f"actor{i}",
                    {
                        "old_lease_id": "L1",
                        "new_lease_id": f"T{i}",
                        "lease_id": f"T{i}",
                        "role": "implementation",
                        "work_unit": "WU-A",
                        "branch": "wu/1",
                        "pr": 1,
                        "start_head": NEXT_HEAD,
                        "planning_snapshot": snapshot("src/a/**"),
                    },
                )
            )
        result = derive(events)
        self.assert_single_winner(result, "T2", CLAIMANTS - 1)
        for rejected in result["rejected_claims"]:
            self.assertEqual(
                rejected["violations"][0]["reason"], "transfer_source_no_longer_active"
            )

    def test_every_replay_prefix_keeps_the_first_claimant(self) -> None:
        events = [assign(i, "WU-A", "src/a/**") for i in range(1, CLAIMANTS + 1)]
        for end in range(1, CLAIMANTS + 1):
            result = derive(events[:end])
            self.assert_single_winner(result, "L1", end - 1)
        # crash/restart: re-deriving the identical log is byte-for-byte stable.
        self.assertEqual(derive(events), derive(list(events)))

    def test_release_then_reclaim_after_a_large_losing_field(self) -> None:
        events = [assign(i, "WU-A", "src/a/**") for i in range(1, CLAIMANTS + 1)]
        events.append(
            event(
                CLAIMANTS + 1,
                "ROLE_LEASE_RELEASED",
                "actor1",
                {"lease_id": "L1", "pr": 1, "reason": "abandoned"},
            )
        )
        events.append(assign(CLAIMANTS + 2, "WU-A", "src/a/**"))
        result = derive(events)
        self.assertEqual(
            [lease["id"] for lease in result["active_leases"]], [f"L{CLAIMANTS + 2}"]
        )
        self.assertEqual(result["integrity_conflicts"], [])
        self.assertEqual(len(result["rejected_claims"]), CLAIMANTS - 1)


if __name__ == "__main__":
    unittest.main()
