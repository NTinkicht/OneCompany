from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lease_lifecycle

UTC = dt.timezone.utc
A = "a" * 40
B = "b" * 40
C = "c" * 40


def instant(seconds: int) -> dt.datetime:
    return dt.datetime(2026, 1, 1, tzinfo=UTC) + dt.timedelta(seconds=seconds)


def event(
    index: int,
    kind: str,
    payload: dict,
    *,
    actor: str = "worker",
    seconds: int | None = None,
) -> dict:
    at = instant(index if seconds is None else seconds)
    return {
        "version": 1,
        "event_id": f"e{index}",
        "type": kind,
        "actor": actor,
        "payload": payload,
        "timestamp": at.isoformat().replace("+00:00", "Z"),
        "local_sequence": index,
    }


def assignment(
    lease_id: str = "L1",
    *,
    head: str = A,
    actor: str = "worker",
    seconds: int = 0,
) -> dict:
    return event(
        1,
        "ROLE_LEASE_ASSIGNED",
        {
            "lease_id": lease_id,
            "role": "implementation",
            "work_unit": "WU-A",
            "branch": "feature/a",
            "pr": 7,
            "start_head": head,
            "planning_snapshot": {
                "write_scope": ["src/a/**"],
                "resource_locks": [],
                "parallelism": "auto",
                "risk_class": "LOW",
                "dependencies": [],
                "dependency_closure": [],
            },
        },
        actor=actor,
        seconds=seconds,
    )


def base_view(*_args, **_kwargs) -> dict:
    return {
        "active_leases": [],
        "material_authors": [],
        "material_authors_by_pr": {},
        "current_gate": None,
        "gates_by_pr": {},
        "rejected_claims": [],
        "integrity_conflicts": [],
        "conflicts": [],
        "resolved_conflict_ids": [],
        "merged_work_units": [],
        "verified_merged_work_units": [],
        "current_actor_eligibility": {},
    }


def policy(ttl: int = 100) -> dict:
    return {
        "ttl_seconds": ttl,
        "renewal_progress_kinds": ["pr_head"],
        "implicit_expiry_revokes_authority": True,
    }


def initial_lease() -> dict:
    assigned = assignment()
    return lease_lifecycle._lease_from_event(
        assigned,
        assigned["payload"],
        policy=policy(),
        policy_blob_sha=None,
    )


class LeaseLifecycleTests(unittest.TestCase):
    def derive(self, events, *, now):
        with (
            patch.object(
                lease_lifecycle.ledger_lib,
                "derive",
                side_effect=base_view,
            ),
            patch.object(
                lease_lifecycle,
                "lifecycle_policy",
                side_effect=policy,
            ),
        ):
            return lease_lifecycle.derive_lifecycle(
                events,
                now=now,
                durable=False,
            )

    def test_assignment_has_deterministic_issue_and_expiry_and_implicit_expiry_revokes_authority(self):
        live = self.derive([assignment()], now=instant(99))
        self.assertEqual(
            [item["id"] for item in live["active_leases"]],
            ["L1"],
        )
        self.assertEqual(
            live["active_leases"][0]["issued_at"],
            "2026-01-01T00:00:00Z",
        )
        self.assertEqual(
            live["active_leases"][0]["expires_at"],
            "2026-01-01T00:01:40Z",
        )

        expired = self.derive([assignment()], now=instant(100))
        self.assertEqual(expired["active_leases"], [])
        self.assertEqual(
            [item["id"] for item in expired["expired_leases"]],
            ["L1"],
        )
        self.assertEqual(
            expired["lease_history"][0]["work_unit"],
            "WU-A",
        )
        self.assertEqual(expired["material_authors"], ["worker"])

    def test_durable_assignment_uses_frozen_base_policy_not_candidate_local_ttl(self):
        with (
            patch.object(
                lease_lifecycle.ledger_lib,
                "derive",
                side_effect=base_view,
            ),
            patch.object(
                lease_lifecycle,
                "lifecycle_policy",
                return_value=policy(10_000),
            ),
            patch.object(
                lease_lifecycle,
                "_policy_for_event",
                return_value=(policy(100), "base-ledger-blob", None),
            ),
        ):
            view = lease_lifecycle.derive_lifecycle(
                [assignment()],
                now=instant(99),
                durable=True,
                verify_admission_provenance=False,
            )
        lease = view["active_leases"][0]
        self.assertEqual(lease["expires_at"], "2026-01-01T00:01:40Z")
        self.assertEqual(lease["lifecycle_policy"]["ttl_seconds"], 100)
        self.assertEqual(
            lease["lifecycle_policy_blob_sha"],
            "base-ledger-blob",
        )

    def test_supervision_heartbeat_never_renews(self):
        heartbeat = event(
            2,
            "SUPERVISION_CHECK",
            {"lease_id": "L1"},
            seconds=90,
        )
        view = self.derive([assignment(), heartbeat], now=instant(101))
        self.assertEqual(view["active_leases"], [])
        self.assertEqual(
            view["expired_leases"][0]["expires_at"],
            "2026-01-01T00:01:40Z",
        )

    def test_verified_progress_renews_monotonically(self):
        lease = initial_lease()
        renewal = event(
            2,
            lease_lifecycle.RENEW_EVENT,
            {
                "lease_id": "L1",
                "pr": 7,
                "work_unit": "WU-A",
                "progress_kind": "pr_head",
                "previous_head": A,
                "new_head": B,
                "lease_fingerprint": lease_lifecycle.lease_fingerprint(lease),
            },
            seconds=90,
        )
        view = self.derive([assignment(), renewal], now=instant(150))
        self.assertEqual(
            [item["id"] for item in view["active_leases"]],
            ["L1"],
        )
        renewed = view["active_leases"][0]
        self.assertEqual(renewed["last_progress_head"], B)
        self.assertEqual(
            renewed["expires_at"],
            "2026-01-01T00:03:10Z",
        )
        self.assertEqual(len(renewed["renewals"]), 1)

    def test_same_head_heartbeat_style_renewal_is_rejected(self):
        lease = initial_lease()
        renewal = event(
            2,
            lease_lifecycle.RENEW_EVENT,
            {
                "lease_id": "L1",
                "progress_kind": "pr_head",
                "previous_head": A,
                "new_head": A,
                "lease_fingerprint": lease_lifecycle.lease_fingerprint(lease),
            },
            seconds=90,
        )
        view = self.derive([assignment(), renewal], now=instant(101))
        self.assertEqual(view["active_leases"], [])
        self.assertIn(
            "heartbeat_or_invalid_local_progress",
            {
                item["reason"]
                for item in view["lifecycle_rejected_claims"]
            },
        )

    def test_renewal_cannot_mutate_immutable_lease_identity_or_scope(self):
        lease = initial_lease()
        forged = dict(lease)
        forged["branch"] = "attacker/branch"
        renewal = event(
            2,
            lease_lifecycle.RENEW_EVENT,
            {
                "lease_id": "L1",
                "progress_kind": "pr_head",
                "previous_head": A,
                "new_head": B,
                "lease_fingerprint": lease_lifecycle.lease_fingerprint(forged),
            },
            seconds=90,
        )
        view = self.derive([assignment(), renewal], now=instant(95))
        current = view["active_leases"][0]
        self.assertEqual(current["branch"], "feature/a")
        self.assertEqual(current["last_progress_head"], A)
        self.assertIn(
            "renew_immutable_lease_mismatch",
            {
                item["reason"]
                for item in view["lifecycle_rejected_claims"]
            },
        )

    def test_renew_before_reap_wins_when_progress_extended_expiry(self):
        lease = initial_lease()
        renewal = event(
            2,
            lease_lifecycle.RENEW_EVENT,
            {
                "lease_id": "L1",
                "progress_kind": "pr_head",
                "previous_head": A,
                "new_head": B,
                "lease_fingerprint": lease_lifecycle.lease_fingerprint(lease),
            },
            seconds=90,
        )
        reap = event(
            3,
            lease_lifecycle.REAP_EVENT,
            {"lease_id": "L1", "reason": "lease_expired"},
            actor="system-reaper",
            seconds=110,
        )
        view = self.derive(
            [assignment(), renewal, reap],
            now=instant(150),
        )
        self.assertEqual(
            [item["id"] for item in view["active_leases"]],
            ["L1"],
        )
        self.assertIn(
            "reap_before_expiry",
            {
                item["reason"]
                for item in view["lifecycle_rejected_claims"]
            },
        )

    def test_reap_before_late_renewal_wins_and_future_work_is_not_deadlocked(self):
        lease = initial_lease()
        reap = event(
            2,
            lease_lifecycle.REAP_EVENT,
            {"lease_id": "L1", "reason": "lease_expired"},
            actor="system-reaper",
            seconds=110,
        )
        late = event(
            3,
            lease_lifecycle.RENEW_EVENT,
            {
                "lease_id": "L1",
                "progress_kind": "pr_head",
                "previous_head": A,
                "new_head": B,
                "lease_fingerprint": lease_lifecycle.lease_fingerprint(lease),
            },
            seconds=120,
        )
        replacement = assignment(
            "L2",
            head=C,
            actor="worker2",
            seconds=130,
        )
        replacement["event_id"] = "e4"
        replacement["local_sequence"] = 4
        view = self.derive(
            [assignment(), reap, late, replacement],
            now=instant(150),
        )
        self.assertEqual(
            [item["id"] for item in view["active_leases"]],
            ["L2"],
        )
        self.assertEqual(
            [item["id"] for item in view["reaped_leases"]],
            ["L1"],
        )
        self.assertIn(
            "renew_source_not_active",
            {
                item["reason"]
                for item in view["lifecycle_rejected_claims"]
            },
        )
        self.assertEqual(
            set(view["material_authors"]),
            {"worker", "worker2"},
        )

    def test_transfer_from_expired_source_cannot_resurrect_authority(self):
        transfer = event(
            2,
            "ROLE_LEASE_TRANSFERRED",
            {
                "old_lease_id": "L1",
                "new_lease_id": "L2",
                "lease_id": "L2",
                "role": "implementation",
                "work_unit": "WU-A",
                "branch": "feature/a",
                "pr": 7,
                "start_head": B,
                "planning_snapshot": assignment()["payload"][
                    "planning_snapshot"
                ],
            },
            actor="worker2",
            seconds=110,
        )
        view = self.derive([assignment(), transfer], now=instant(120))
        self.assertEqual(view["active_leases"], [])
        self.assertIn(
            "lifecycle_transfer_source_expired",
            {
                item["reason"]
                for item in view["lifecycle_rejected_claims"]
            },
        )

    def test_local_event_store_reconstructs_authority_without_state_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            payload = assignment()["payload"]
            with (
                patch.object(
                    lease_lifecycle.ledger_lib,
                    "ledger_enabled",
                    return_value=False,
                ),
                patch.object(
                    lease_lifecycle.ledger_lib,
                    "derive",
                    side_effect=base_view,
                ),
                patch.object(
                    lease_lifecycle,
                    "lifecycle_policy",
                    side_effect=policy,
                ),
            ):
                lease_lifecycle.append_coordination_event(
                    "ROLE_LEASE_ASSIGNED",
                    "worker",
                    payload,
                    now=instant(0),
                    local_path=path,
                )
                first = lease_lifecycle.coordination_view(
                    now=instant(50),
                    local_path=path,
                )
                second = lease_lifecycle.coordination_view(
                    now=instant(50),
                    local_path=path,
                )
            self.assertEqual(
                first["active_leases"],
                second["active_leases"],
            )
            self.assertEqual(first["active_leases"][0]["id"], "L1")
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
