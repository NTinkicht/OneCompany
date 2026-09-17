from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("shadow_migration", ROOT / "scripts" / "shadow_migration.py")
assert SPEC and SPEC.loader
shadow_migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shadow_migration)


class ShadowMigrationTests(unittest.TestCase):
    def test_tabibi_fixture_fails_closed_without_mutation_readiness(self):
        fixture = ROOT / "source-evidence" / "tabibi" / "c1-shadow.json"
        if not fixture.exists():
            self.skipTest("source-only Tabibi fixture is intentionally absent from installed copies")
        report = shadow_migration.analyze_manifest(shadow_migration.load_manifest(fixture))
        self.assertFalse(report["mutation_ready"])
        self.assertTrue(report["shadow_only"])
        self.assertFalse(report["target_mutated"])
        self.assertIn("LIVE_CACHE_DRIFT", report["blocker_codes"])
        self.assertIn("ACTOR_PROTOCOL_DRIFT", report["blocker_codes"])
        self.assertIn("BRANCH_PROTECTION_UNVERIFIED", report["blocker_codes"])
        self.assertIn("DUAL_WRITER_RISK", report["blocker_codes"])
        self.assertIn("CUTOVER_OWNERSHIP_UNRESOLVED", report["blocker_codes"])

    def test_clean_reviewed_snapshot_can_be_reported_ready_for_separate_cutover(self):
        manifest = {
            "project": {"repository": "example/app", "default_branch": "main"},
            "snapshot": {
                "observed_at": "2026-09-17T00:00:00Z",
                "main_sha": "a" * 40,
                "source": "verified-live",
                "stale": False,
                "derived": False,
            },
            "live": {"work_unit": "WU1", "pr": 10, "pr_head": "b" * 40},
            "legacy": {
                "state": {"work_unit": "WU1", "current_pr": 10},
                "work_queue": {"work_unit": "WU1"},
                "registry": {"active_actors": ["chatgpt", "claude"]},
                "protocol": {"active_actors": ["chatgpt", "claude"]},
            },
            "branch_protection": {"verified": True, "protected": True},
            "incumbent_writers": [
                {
                    "name": "legacy-event-owner",
                    "active": True,
                    "mutation_capable": True,
                    "reviewed": True,
                    "capabilities": ["event_handoff"],
                }
            ],
            "cutover": {"owner_by_capability": {"event_handoff": "legacy-event-owner"}},
            "proposed_onecompany": {"mode": "shadow", "mutation_capable": False},
            "cutover_evidence": {
                "active_stream_status": "confirmed",
                "surface_classifications_reviewed": True,
                "rollback_verified": True,
                "human_decisions_resolved": True,
                "zero_extra_spend": True,
                "autonomy_level": "L1",
                "staging_branch": "epic-0.6-integration",
                "fresh_c2_reconciliation": True,
            },
        }
        report = shadow_migration.analyze_manifest(manifest)
        self.assertTrue(report["mutation_ready"])
        self.assertEqual(report["blocker_codes"], [])
        self.assertFalse(report["target_mutated"])

    def test_analysis_does_not_modify_manifest_file(self):
        manifest = {
            "project": {"repository": "example/app", "default_branch": "main"},
            "snapshot": {"observed_at": "now", "main_sha": "c" * 40, "source": "fixture"},
            "live": {"work_unit": "WU1", "pr": 1, "pr_head": "d" * 40},
            "legacy": {
                "state": {"work_unit": "WU1", "current_pr": 1},
                "work_queue": {"work_unit": "WU1"},
                "registry": {"active_actors": ["chatgpt"]},
                "protocol": {"active_actors": ["chatgpt"]},
            },
            "branch_protection": {"verified": True, "protected": True},
            "incumbent_writers": [],
            "cutover": {"owner_by_capability": {"none": "none"}},
            "proposed_onecompany": {"mode": "shadow", "mutation_capable": False},
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            original = json.dumps(manifest, indent=2) + "\n"
            path.write_text(original, encoding="utf-8")
            shadow_migration.analyze_manifest(shadow_migration.load_manifest(path))
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_missing_provenance_fails_closed(self):
        report = shadow_migration.analyze_manifest(
            {
                "project": {"repository": "example/app", "default_branch": "main"},
                "snapshot": {},
                "live": {},
                "legacy": {},
                "branch_protection": {},
                "incumbent_writers": [],
                "cutover": {},
                "proposed_onecompany": {"mode": "shadow", "mutation_capable": False},
            }
        )
        self.assertFalse(report["mutation_ready"])
        self.assertIn("SNAPSHOT_PROVENANCE_INCOMPLETE", report["blocker_codes"])
        self.assertIn("LIVE_STREAM_IDENTITY_INCOMPLETE", report["blocker_codes"])


if __name__ == "__main__":
    unittest.main()
