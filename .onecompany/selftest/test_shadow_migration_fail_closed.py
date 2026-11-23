from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("shadow_migration", ROOT / "scripts" / "shadow_migration.py")
assert SPEC and SPEC.loader
shadow_migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shadow_migration)


def verified_idle_manifest() -> dict:
    boundary = "2026-09-18T12:00:00Z"
    sha = "a" * 40
    return {
        "schema_version": "1.0",
        "project": {"repository": "example/idle-app", "default_branch": "main"},
        "snapshot": {"observed_at": boundary, "main_sha": sha, "source": "verified-live", "stale": False, "derived": False},
        "live": {"mode": "idle", "idle": {"verified": True, "open_pr_count": 0, "active_work_unit_count": 0, "evidence_ref": "github:idle-stream-evidence", "snapshot_sha": sha}},
        "legacy": {"mode": "absent", "control_plane_absence": {"verified": True, "evidence_ref": "github:no-legacy-control-plane", "snapshot_sha": sha}},
        "branch_protection": {"verified": True, "protected": True},
        "incumbent_writer_inventory_complete": True,
        "incumbent_writers": [],
        "no_active_mutation_writers_verified": True,
        "cutover": {"owner_by_capability": {}},
        "proposed_onecompany": {"mode": "shadow", "mutation_capable": False},
        "cutover_evidence": {"active_stream_status": "confirmed", "surface_classifications_reviewed": True, "rollback_verified": True, "human_decisions_resolved": True, "zero_extra_spend": True, "autonomy_level": "L1", "staging_branch": "epic-0.6-integration", "fresh_c2_reconciliation": True},
    }


class ShadowMigrationFailClosedTests(unittest.TestCase):
    def test_absent_mode_rejects_malformed_legacy_state(self):
        manifest = verified_idle_manifest()
        manifest["legacy"]["state"] = ["present"]
        report = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(report["mutation_ready"])
        self.assertIn("LEGACY_CONTROL_PLANE_ABSENCE_CONFLICT", report["blocker_codes"])

    def test_absent_mode_rejects_non_string_actor_entries(self):
        manifest = verified_idle_manifest()
        manifest["legacy"]["registry"] = {"active_actors": [123]}
        report = shadow_migration.analyze_manifest(manifest)
        self.assertFalse(report["mutation_ready"])
        self.assertIn("LEGACY_CONTROL_PLANE_ABSENCE_CONFLICT", report["blocker_codes"])

    def test_duplicate_key_manifest_is_refused_not_last_wins(self):
        import json
        import tempfile

        good = json.dumps(verified_idle_manifest())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            path.write_text(good, encoding="utf-8")
            self.assertEqual(shadow_migration.load_manifest(path)["schema_version"], "1.0")
            path.write_text(good[:-1] + ', "schema_version": "2.0"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                shadow_migration.load_manifest(path)


if __name__ == "__main__":
    unittest.main()
