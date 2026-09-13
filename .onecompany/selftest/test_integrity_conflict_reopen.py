from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger_lib import derive


def event(i: int, kind: str, actor: str, payload: dict, *, event_id: str) -> dict:
    return {
        "version": 1,
        "event_id": event_id,
        "type": kind,
        "actor": actor,
        "payload": payload,
        "github_created_at": f"2026-01-01T00:00:{i:02d}Z",
        "github_comment_id": i,
    }


class IntegrityConflictReopenTests(unittest.TestCase):
    def test_later_recurrence_reopens_previously_resolved_conflict(self):
        conflict_id = "dup:duplicate_event_id_ignored"
        events = [
            event(1, "SUPERVISION_CHECK", "chatgpt", {"state": "first"}, event_id="dup"),
            event(2, "SUPERVISION_CHECK", "chatgpt", {"state": "duplicate"}, event_id="dup"),
            event(
                3,
                "INTEGRITY_CONFLICT_RESOLVED",
                "human-owner",
                {"conflict_id": conflict_id, "reason": "investigated"},
                event_id="resolve-1",
            ),
        ]

        resolved = derive(events)
        self.assertEqual(resolved["integrity_conflicts"], [])
        self.assertIn(conflict_id, resolved["resolved_conflict_ids"])

        events.append(
            event(4, "SUPERVISION_CHECK", "chatgpt", {"state": "duplicate-again"}, event_id="dup")
        )
        reopened = derive(events)

        self.assertEqual(len(reopened["integrity_conflicts"]), 1)
        self.assertEqual(reopened["integrity_conflicts"][0]["conflict_id"], conflict_id)
        self.assertEqual(reopened["integrity_conflicts"][0]["reason"], "duplicate_event_id_ignored")


if __name__ == "__main__":
    unittest.main()
