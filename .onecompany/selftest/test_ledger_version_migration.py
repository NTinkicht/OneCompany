from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger_lib


def comment(comment_id: int, version: int) -> dict:
    event = {
        "version": version,
        "event_id": f"e-{comment_id}",
        "type": "SUPERVISION_CHECK",
        "actor": "worker",
        "payload": {"state": "ok"},
    }
    body = (
        f"{ledger_lib.MARKER}\n```json\n"
        f"{json.dumps(event, separators=(',', ':'))}\n```\n"
    )
    return {
        "id": comment_id,
        "user": {"login": "trusted-bot"},
        "body": body,
        "created_at": "2026-09-13T00:00:00Z",
        "updated_at": "2026-09-13T00:00:00Z",
        "html_url": f"https://example.invalid/{comment_id}",
    }


class LedgerVersionMigrationTests(unittest.TestCase):
    def config(self) -> dict:
        return {
            "event_format_version": 2,
            "accepted_event_versions": [1, 2],
            "legacy_event_max_comment_id": 100,
            "accepted_event_types": ["SUPERVISION_CHECK"],
        }

    def test_pre_cutoff_v1_event_is_readable(self):
        with (
            patch.object(ledger_lib, "_assert_ledger_runtime_activation"),
            patch.object(ledger_lib, "_repo_and_issue", return_value=("o/r", 1)),
            patch.object(ledger_lib, "ledger_config", return_value=self.config()),
            patch.object(ledger_lib, "_trusted_publishers", return_value={"trusted-bot"}),
            patch.object(ledger_lib, "_gh_json", return_value=[[comment(100, 1)]]),
        ):
            events = ledger_lib.list_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["version"], 1)

    def test_post_cutoff_v1_event_fails_closed(self):
        with (
            patch.object(ledger_lib, "_assert_ledger_runtime_activation"),
            patch.object(ledger_lib, "_repo_and_issue", return_value=("o/r", 1)),
            patch.object(ledger_lib, "ledger_config", return_value=self.config()),
            patch.object(ledger_lib, "_trusted_publishers", return_value={"trusted-bot"}),
            patch.object(ledger_lib, "_gh_json", return_value=[[comment(101, 1)]]),
        ):
            with self.assertRaisesRegex(RuntimeError, "post-cutoff legacy"):
                ledger_lib.list_events()


if __name__ == "__main__":
    unittest.main()
