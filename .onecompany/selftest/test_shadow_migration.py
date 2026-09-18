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


def verified_idle_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "project": {"repository": "example/idle-app", "default_branch": "main"},
        "snapshot": {
            "observed_at": "2026-09-18T12:00:00Z",
            "main_sha": "a" * 40,
            "source": "verified-live",
            "stale": False,
            "derived": False,
        },
        "live": {
            "mode": "idle",
            "idle": {
                "verified": True,
                "open_pr_count": 0,
                "active_work_unit_count": 0,
                "evidence_ref": "github:idle-stream-evidence",
                "snapshot_sha": "a" * 40,
            },
        },
        "legacy": {
            "mode": "absent",
            "control_plane_absence": {
                "verified": True,
                "evidence_ref": "github:no-legacy-control-plane",
                "snapshot_sha": "a" * 40,
            },
        },
        "branch_protection": {"verified": True, "protected": True},
        "incumbent_writer_inventory_complete": True,
        "incumbent_writers": [],
        "no_active_mutation_writers_verified": True,
        "cutover": {"owner_by_capability": {}},
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
            "schema_version": "1.0",
            "project": {"repository": "example/app", "default_branch": "main"},
            "snapshot": {"observed_at": "2026-09-17T00:00:00Z", "main_sha": "a" * 40, "source": "verified-live", "stale": False, "derived": False},
            "live": {"work_unit": "WU1", "pr": 10, "pr_head": "b" * 40},
            "legacy": {"state": {"work_unit": "WU1", "current_pr": 10}, "work_queue": {"work_unit": "WU1"}, "registry": {"active_actors": ["chatgpt", "claude"]}, "protocol": {"active_actors": ["chatgpt", "claude"]}},
            "branch_protection": {"verified": True, "protected": True},
            "incumbent_writer_inventory_complete": True,
            "incumbent_writers": [{"name": "legacy-event-owner", "active": True, "mutation_capable": True, "reviewed": True, "capabilities": ["event_handoff"]}],
            "cutover": {"owner_by_capability": {"event_handoff": "legacy-event-owner"}},
            "proposed_onecompany": {"mode": "shadow", "mutation_capable": False},
            "cutover_evidence": {"active_stream_status": "confirmed", "surface_classifications_reviewed": True, "rollback_verified": True, "human_decisions_resolved": True, "zero_extra_spend": True, "autonomy_level": "L1", "staging_branch": "epic-0.6-integration", "fresh_c2_reconciliation": True},
        }
        report = shadow_migration.analyze_manifest(manifest)
        self.assertTrue(report["mutation_ready"])
        self.assertEqual(report["blocker_codes"], [])
        self.assertFalse(report["target_mutated"])
        manifest["live"]["pr_head"] = "x"
        malformed_head = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(malformed_head["mutation_ready"])
        self.assertIn("LIVE_STREAM_IDENTITY_INCOMPLETE", malformed_head["blocker_codes"])
        manifest["live"]["pr_head"] = "b" * 40
        manifest["schema_version"] = "2.0"
        unsupported_schema = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(unsupported_schema["mutation_ready"])
        self.assertIn("SCHEMA_VERSION_UNSUPPORTED", unsupported_schema["blocker_codes"])

    def test_verified_idle_target_needs_no_synthetic_live_stream_or_actor_roster(self):
        report = shadow_migration.analyze_manifest(verified_idle_manifest())
        self.assertTrue(report["mutation_ready"])
        self.assertEqual(report["stream_mode"], "idle")
        self.assertEqual(report["legacy_mode"], "absent")
        self.assertEqual(report["blocker_codes"], [])

    def test_idle_target_with_open_pull_request_fails_closed(self):
        manifest = verified_idle_manifest(); manifest["live"]["idle"]["open_pr_count"] = 1
        report = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(report["mutation_ready"]); self.assertIn("IDLE_STREAM_EVIDENCE_INCOMPLETE", report["blocker_codes"])

    def test_idle_target_requires_exact_snapshot_binding(self):
        manifest = verified_idle_manifest(); manifest["live"]["idle"]["snapshot_sha"] = "b" * 40
        report = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(report["mutation_ready"]); self.assertIn("IDLE_STREAM_EVIDENCE_INCOMPLETE", report["blocker_codes"])

    def test_idle_mode_rejects_populated_active_stream_identity(self):
        manifest = verified_idle_manifest(); manifest["live"].update({"pr": 99, "pr_head": "b" * 40, "work_unit": "WU-FAKE"})
        report = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(report["mutation_ready"]); self.assertIn("IDLE_STREAM_STATE_CONFLICT", report["blocker_codes"])

    def test_absent_legacy_control_plane_requires_verified_evidence(self):
        manifest = verified_idle_manifest(); manifest["legacy"]["control_plane_absence"]["verified"] = False
        report = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(report["mutation_ready"]); self.assertIn("LEGACY_CONTROL_PLANE_ABSENCE_UNVERIFIED", report["blocker_codes"])

    def test_absent_legacy_control_plane_rejects_state_or_queue_conflict(self):
        manifest = verified_idle_manifest(); manifest["legacy"]["state"] = {"work_unit": "WU-STALE"}; manifest["legacy"]["work_queue"] = {"work_unit": "WU-STALE"}
        report = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(report["mutation_ready"]); self.assertIn("LEGACY_CONTROL_PLANE_ABSENCE_CONFLICT", report["blocker_codes"])

    def test_absent_legacy_control_plane_rejects_actor_roster_conflict(self):
        manifest = verified_idle_manifest(); manifest["legacy"]["registry"] = {"active_actors": ["bot"]}
        report = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(report["mutation_ready"]); self.assertIn("LEGACY_CONTROL_PLANE_ABSENCE_CONFLICT", report["blocker_codes"])

    def test_idle_target_with_active_mutation_writer_fails_closed(self):
        manifest = verified_idle_manifest()
        manifest["incumbent_writers"] = [{"name": "external-writer", "active": True, "mutation_capable": True, "reviewed": True, "capabilities": ["deployment"]}]
        manifest["no_active_mutation_writers_verified"] = False
        manifest["cutover"]["owner_by_capability"] = {"deployment": "external-writer"}
        report = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(report["mutation_ready"]); self.assertIn("IDLE_STREAM_WRITER_CONFLICT", report["blocker_codes"])

    def test_explicit_adoption_blockers_propagate(self):
        manifest = verified_idle_manifest(); manifest["adoption_blockers"] = [{"code": "NO_CI", "message": "repository-native CI is not established"}]
        report = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(report["mutation_ready"]); self.assertIn("NO_CI", report["blocker_codes"])

    def test_veritas_idle_fixture_preserves_c1_blockers_without_fake_live_state(self):
        fixture = ROOT / "source-evidence" / "veritas-atlas" / "c2a-shadow.json"
        if not fixture.exists():
            self.skipTest("source-only Veritas fixture is intentionally absent from installed copies")
        report = shadow_migration.analyze_manifest(shadow_migration.load_manifest(fixture))
        self.assertFalse(report["mutation_ready"])
        self.assertTrue(report["shadow_only"])
        self.assertFalse(report["target_mutated"])
        self.assertEqual(report["stream_mode"], "idle")
        self.assertEqual(report["legacy_mode"], "absent")
        self.assertNotIn("LIVE_STREAM_IDENTITY_INCOMPLETE", report["blocker_codes"])
        self.assertNotIn("ACTOR_PROVENANCE_INCOMPLETE", report["blocker_codes"])
        self.assertIn("DEFAULT_BRANCH_UNPROTECTED", report["blocker_codes"])
        self.assertIn("MUTATION_WRITER_INVENTORY_UNVERIFIED", report["blocker_codes"])
        self.assertIn("NO_REPOSITORY_CI_WORKFLOW", report["blocker_codes"])

    def test_analysis_does_not_modify_manifest_file(self):
        manifest = {"project": {"repository": "example/app", "default_branch": "main"}, "snapshot": {"observed_at": "now", "main_sha": "c" * 40, "source": "fixture"}, "live": {"work_unit": "WU1", "pr": 1, "pr_head": "d" * 40}, "legacy": {"state": {"work_unit": "WU1", "current_pr": 1}, "work_queue": {"work_unit": "WU1"}, "registry": {"active_actors": ["chatgpt"]}, "protocol": {"active_actors": ["chatgpt"]}}, "branch_protection": {"verified": True, "protected": True}, "incumbent_writers": [], "cutover": {"owner_by_capability": {"none": "none"}}, "proposed_onecompany": {"mode": "shadow", "mutation_capable": False}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"; original = json.dumps(manifest, indent=2) + "\n"; path.write_text(original, encoding="utf-8")
            shadow_migration.analyze_manifest(shadow_migration.load_manifest(path)); self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_missing_provenance_fails_closed(self):
        report = shadow_migration.analyze_manifest({"project": {"repository": "example/app", "default_branch": "main"}, "snapshot": {}, "live": {}, "legacy": {}, "branch_protection": {}, "incumbent_writers": [], "cutover": {}, "proposed_onecompany": {"mode": "shadow", "mutation_capable": False}})
        self.assertFalse(report["mutation_ready"])
        self.assertIn("SNAPSHOT_PROVENANCE_INCOMPLETE", report["blocker_codes"])
        self.assertIn("LIVE_STREAM_IDENTITY_INCOMPLETE", report["blocker_codes"])


if __name__ == "__main__":
    unittest.main()
