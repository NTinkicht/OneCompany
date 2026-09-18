from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "cutover_readiness", SCRIPTS / "cutover_readiness.py"
)
assert SPEC and SPEC.loader
cutover_readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cutover_readiness)


def clean_manifest(*, human_approved: bool = True) -> dict:
    return {
        "schema_version": "1.0",
        "project": {"repository": "example/app", "default_branch": "main"},
        "snapshot": {
            "observed_at": "2026-09-18T01:00:00Z",
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
        "incumbent_writer_inventory_complete": True,
        "incumbent_writers": [{
            "name": "legacy-event-owner", "active": False,
            "mutation_capable": True, "reviewed": True,
            "capabilities": ["event_handoff"],
            "quiesced_at": "2026-09-18T00:55:00Z",
            "quiescence_evidence_ref": "github:legacy-supervisor-disabled",
        }],
        "cutover": {
            "owner_by_capability": {"event_handoff": "legacy-event-owner"},
            "active_stream": {
                "status": "quiesced", "active_writer_count": 0,
                "evidence_ref": "github:stream-quiesced",
                "quiesced_at": "2026-09-18T00:57:00Z",
            },
            "reconciled_after_quiescence": True,
            "reconciliation_completed_at": "2026-09-18T00:59:00Z",
            "reconciliation_evidence_ref": "github:reconciliation-run-1",
            "reconciliation_snapshot_sha": "a" * 40,
            "reconciliation_pr_head": "b" * 40,
            "owner_by_capability_after_cutover": {"event_handoff": "onecompany"},
            "rollback": {
                "onecompany_disable_first": True,
                "legacy_restore_requires_human": True,
                "restore_order_reviewed": True,
                "evidence_ref": "docs:rollback-plan",
            },
            "human_gate": {
                "required": True, "approved": human_approved,
                "approver_type": "human" if human_approved else None,
                "approver_identity": "reviewer@example" if human_approved else None,
                "principal_evidence": {
                    "identity": "reviewer@example",
                    "principal_type": "human",
                    "verified": True,
                    "evidence_ref": "github:verified-reviewer",
                } if human_approved else None,
                "approval_ref": "github:human-decision-1" if human_approved else None,
                "approved_at": "2026-09-18T01:02:00Z" if human_approved else None,
                "approved_reconciliation_evidence_ref": "github:reconciliation-run-1" if human_approved else None,
                "approved_snapshot_sha": "a" * 40,
                "approved_pr_head": "b" * 40,
            },
        },
        "proposed_onecompany": {
            "mode": "shadow", "mutation_capable": False,
            "writer_identity": "onecompany", "writer_reviewed": True,
            "writer_evidence_ref": "github:onecompany-writer-review",
        },
        "cutover_evidence": {
            "active_stream_status": "confirmed",
            "surface_classifications_reviewed": True,
            "rollback_verified": True, "human_decisions_resolved": True,
            "zero_extra_spend": True, "autonomy_level": "L1",
            "staging_branch": "epic-0.6-integration",
            "fresh_c2_reconciliation": True,
        },
    }


class CutoverReadinessTests(unittest.TestCase):
    def test_clean_reviewed_manifest_is_ready_but_never_authorized(self):
        report = cutover_readiness.analyze_cutover(clean_manifest())
        self.assertTrue(report["shadow_mutation_ready"])
        self.assertTrue(report["cutover_ready"])
        self.assertFalse(report["target_mutated"])
        self.assertFalse(report["mutation_authorized"])
        self.assertEqual(report["authority_effects"], [])
        self.assertEqual(report["blocker_codes"], [])

    def test_verified_empty_incumbent_inventory_can_be_ready(self):
        manifest = clean_manifest()
        manifest["incumbent_writers"] = []
        manifest["no_active_mutation_writers_verified"] = True
        manifest["cutover"]["owner_by_capability"] = {}
        manifest["cutover"]["owner_by_capability_after_cutover"] = {}
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertTrue(report["shadow_mutation_ready"])
        self.assertTrue(report["cutover_ready"])
        self.assertEqual(report["mutation_capabilities"], [])
        self.assertNotIn("POST_CUTOVER_OWNERSHIP_UNRESOLVED", report["blocker_codes"])

    def test_human_principal_evidence_identity_must_match(self):
        manifest = clean_manifest()
        manifest["cutover"]["human_gate"]["principal_evidence"]["identity"] = "someone-else@example"
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"])
        self.assertIn("HUMAN_CUTOVER_APPROVAL_MISSING", report["blocker_codes"])

    def test_human_principal_evidence_must_be_human(self):
        manifest = clean_manifest()
        manifest["cutover"]["human_gate"]["principal_evidence"]["principal_type"] = "service-account"
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"])
        self.assertIn("HUMAN_CUTOVER_APPROVAL_MISSING", report["blocker_codes"])

    def test_human_principal_evidence_is_required(self):
        manifest = clean_manifest()
        manifest["cutover"]["human_gate"].pop("principal_evidence")
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"])
        self.assertIn("HUMAN_CUTOVER_APPROVAL_MISSING", report["blocker_codes"])

    def test_human_unapproved_manifest_stays_blocked(self):
        report = cutover_readiness.analyze_cutover(clean_manifest(human_approved=False))
        self.assertFalse(report["cutover_ready"])
        self.assertIn("HUMAN_CUTOVER_APPROVAL_MISSING", report["blocker_codes"])

    def test_human_approval_must_follow_reconciliation(self):
        manifest = clean_manifest(); manifest["cutover"]["human_gate"]["approved_at"] = "2026-09-18T00:58:00Z"
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"])
        self.assertIn("HUMAN_CUTOVER_APPROVAL_MISSING", report["blocker_codes"])

    def test_human_approval_equal_to_reconciliation_is_rejected(self):
        manifest = clean_manifest(); manifest["cutover"]["human_gate"]["approved_at"] = manifest["cutover"]["reconciliation_completed_at"]
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"])
        self.assertIn("HUMAN_CUTOVER_APPROVAL_MISSING", report["blocker_codes"])

    def test_timezone_less_human_approval_is_rejected(self):
        manifest = clean_manifest(); manifest["cutover"]["human_gate"]["approved_at"] = "2026-09-18T01:02:00"
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"])
        self.assertIn("HUMAN_CUTOVER_APPROVAL_MISSING", report["blocker_codes"])

    def test_human_approval_must_bind_reconciliation_evidence(self):
        manifest = clean_manifest(); manifest["cutover"]["human_gate"]["approved_reconciliation_evidence_ref"] = "github:some-other-reconciliation"
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"])
        self.assertIn("HUMAN_CUTOVER_APPROVAL_MISSING", report["blocker_codes"])

    def test_active_incumbent_mutator_blocks_cutover(self):
        manifest = clean_manifest(); manifest["incumbent_writers"][0]["active"] = True
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("INCUMBENT_MUTATORS_STILL_ACTIVE", report["blocker_codes"])

    def test_unreviewed_incumbent_mutator_blocks_cutover(self):
        manifest = clean_manifest(); manifest["incumbent_writers"][0]["reviewed"] = False
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("INCUMBENT_MUTATOR_UNREVIEWED", report["blocker_codes"])

    def test_missing_quiescence_evidence_blocks_cutover(self):
        manifest = clean_manifest(); manifest["incumbent_writers"][0].pop("quiescence_evidence_ref")
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("QUIESCENCE_EVIDENCE_INCOMPLETE", report["blocker_codes"])

    def test_snapshot_must_follow_all_quiescence_events(self):
        manifest = clean_manifest(); manifest["incumbent_writers"][0]["quiesced_at"] = "2026-09-18T01:05:00Z"
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("POST_QUIESCENCE_RECONCILIATION_REQUIRED", report["blocker_codes"])

    def test_timezone_less_quiescence_timestamp_is_rejected(self):
        manifest = clean_manifest(); manifest["incumbent_writers"][0]["quiesced_at"] = "2026-09-18T00:55:00"
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("QUIESCENCE_EVIDENCE_INCOMPLETE", report["blocker_codes"])

    def test_timezone_less_reconciliation_timestamp_is_rejected(self):
        manifest = clean_manifest(); manifest["cutover"]["reconciliation_completed_at"] = "2026-09-18T00:59:00"
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("POST_QUIESCENCE_RECONCILIATION_REQUIRED", report["blocker_codes"])

    def test_reconciliation_must_bind_exact_snapshot_and_pr_head(self):
        manifest = clean_manifest(); manifest["cutover"]["reconciliation_pr_head"] = "c" * 40
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("POST_QUIESCENCE_RECONCILIATION_REQUIRED", report["blocker_codes"])

    def test_reconciliation_completion_must_follow_quiescence(self):
        manifest = clean_manifest(); manifest["cutover"]["reconciliation_completed_at"] = "2026-09-18T00:50:00Z"
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("POST_QUIESCENCE_RECONCILIATION_REQUIRED", report["blocker_codes"])

    def test_reconciliation_requires_evidence_reference(self):
        manifest = clean_manifest(); manifest["cutover"].pop("reconciliation_evidence_ref")
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("POST_QUIESCENCE_RECONCILIATION_REQUIRED", report["blocker_codes"])

    def test_active_stream_requires_zero_writer_boundary(self):
        manifest = clean_manifest(); manifest["cutover"]["active_stream"]["active_writer_count"] = 1
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("ACTIVE_STREAM_NOT_QUIESCENT", report["blocker_codes"])

    def test_boolean_false_is_not_a_zero_writer_count(self):
        manifest = clean_manifest(); manifest["cutover"]["active_stream"]["active_writer_count"] = False
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("ACTIVE_STREAM_NOT_QUIESCENT", report["blocker_codes"])

    def test_stream_quiescence_must_precede_reconciliation(self):
        manifest = clean_manifest(); manifest["cutover"]["active_stream"]["quiesced_at"] = "2026-09-18T01:01:00Z"
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("POST_QUIESCENCE_RECONCILIATION_REQUIRED", report["blocker_codes"])

    def test_active_stream_requires_quiescence_timestamp(self):
        manifest = clean_manifest(); manifest["cutover"]["active_stream"].pop("quiesced_at")
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("ACTIVE_STREAM_NOT_QUIESCENT", report["blocker_codes"])

    def test_post_cutover_ownership_must_be_exact_and_single(self):
        manifest = clean_manifest(); manifest["cutover"]["owner_by_capability_after_cutover"] = {"event_handoff": "legacy-event-owner"}
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("POST_CUTOVER_OWNERSHIP_UNRESOLVED", report["blocker_codes"])

    def test_proposed_writer_requires_reviewed_evidence(self):
        manifest = clean_manifest(); manifest["proposed_onecompany"]["writer_reviewed"] = False
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("PROPOSED_WRITER_UNREVIEWED", report["blocker_codes"])

    def test_rollback_plan_is_mandatory(self):
        manifest = clean_manifest(); manifest["cutover"]["rollback"]["onecompany_disable_first"] = False
        report = cutover_readiness.analyze_cutover(manifest)
        self.assertFalse(report["cutover_ready"]); self.assertIn("ROLLBACK_PLAN_INCOMPLETE", report["blocker_codes"])

    def test_c2a_blockers_propagate_fail_closed(self):
        fixture = ROOT / "source-evidence" / "tabibi" / "c1-shadow.json"
        if not fixture.exists(): self.skipTest("source-only Tabibi fixture is intentionally absent")
        report = cutover_readiness.analyze_cutover(cutover_readiness.load_manifest(fixture))
        self.assertFalse(report["shadow_mutation_ready"]); self.assertFalse(report["cutover_ready"])
        self.assertIn("SHADOW_READINESS_REQUIRED", report["blocker_codes"])
        self.assertFalse(report["target_mutated"]); self.assertFalse(report["mutation_authorized"])

    def test_analysis_does_not_modify_manifest_file(self):
        manifest = clean_manifest()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"; path.write_text(json.dumps(manifest), encoding="utf-8")
            before = path.read_bytes(); cutover_readiness.analyze_cutover(cutover_readiness.load_manifest(path)); after = path.read_bytes()
            self.assertEqual(before, after)

    def test_report_is_deterministic(self):
        manifest = clean_manifest(); first = cutover_readiness.analyze_cutover(deepcopy(manifest)); second = cutover_readiness.analyze_cutover(deepcopy(manifest))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
