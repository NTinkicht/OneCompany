"""End-to-end read-only composition of actual Phase-1 smoke and quality evidence."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "phase1_mission_evidence.py"
VIEW = ROOT / "scripts" / "mission_control_local.py"
PROJECTION = ROOT / "scripts" / "mission_control_projection.py"
SOURCE_ONLY = HELPER.is_file() and VIEW.is_file() and PROJECTION.is_file()

if SOURCE_ONLY:
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("phase1_mission_evidence", HELPER)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    from mission_control_local import render


def smoke_fixture() -> dict:
    """Model the schema produced by the actual Phase-1 disposable CRUD runner."""
    return {
        "schema": "onecompany.phase1-vertical-smoke.v1",
        "status": "LOCAL_FIXTURE_PROVEN_ONLY",
        "path": "adopt",
        "project": {
            "name": "Existing checklist", "target": "/tmp/example",
            "repository": "NTinkicht/disposable", "default_branch": "main",
        },
        "owner_brief": "VALID_DRAFT_NOT_APPROVED",
        "planning": {"mode": "READ_ONLY_PROPOSAL", "authorization": "NOT_GRANTED"},
        "source_refs_unverified": {"head": "a" * 40, "base": "b" * 40},
        "real_local_http": {
            "status": "PASS", "health": "PASS", "fixture_discarded": True,
            "flow": "create_list_complete_delete_and_negative_refusals",
        },
        "owner_implementation_approved": False,
        "canonical_work_unit": None,
        "run_key": None,
        "lease_id": None,
        "deployable": False,
        "requested_extra_spend": 0,
    }


def quality_fixture() -> dict:
    """Model the separate exact clean-checkout quality producer's result."""
    return {
        "schema": "onecompany.local-quality-evidence.v1",
        "revision": "a" * 40, "status": "PASS",
        "scope": "real_local_http_ui",
        "test": ".onecompany/selftest/test_vertical_slice.py",
        "deployable": False,
    }


@unittest.skipUnless(SOURCE_ONLY, "source-only Phase-1 dashboard bridge absent from installed target")
class Phase1MissionEvidenceTests(unittest.TestCase):
    def test_without_quality_remains_blocked_and_no_false_gates(self):
        """Local CRUD success alone never fabricates quality, CI, browser or approval."""
        result = bridge.compose(smoke_fixture(), "a" * 40)
        self.assertEqual(result["readiness"], "BLOCKED")
        self.assertEqual(result["checks"]["quality"]["status"], "BLOCKED")
        self.assertEqual(result["checks"]["app"]["status"], "BLOCKED")
        self.assertEqual(result["checks"]["preview"]["status"], "BLOCKED")
        self.assertIs(result["authority_granted"], False)
        self.assertIs(result["local_fixture_discarded"], True)
        self.assertNotIn("preview_url", result)
        page = render(result).decode()
        self.assertIn("NOT READY", page)
        self.assertIn("Quality</strong>: BLOCKED", page)
        self.assertIn("CI</strong>: UNKNOWN", page)
        self.assertIn("Review</strong>: UNKNOWN", page)
        self.assertIn("Browser</strong>: UNKNOWN", page)

    def test_real_local_quality_is_displayed_but_still_not_authority(self):
        """A real separate exact-checkout quality record permits only preview projection."""
        result = bridge.compose(smoke_fixture(), "a" * 40, quality_fixture())
        self.assertEqual(result["readiness"], "BLOCKED")
        self.assertEqual(result["checks"]["quality"]["status"], "BLOCKED")
        self.assertFalse(result["authority_granted"])
        self.assertTrue(result["source_refs_unverified"])
        self.assertNotIn("preview_url", result)
        page = render(result).decode()
        self.assertIn("id='status'>NOT READY", page)
        self.assertIn("No execution or deployment authority", page)
        self.assertIn("Projection fields are unverified input", page)

    def test_hand_authored_schema_valid_json_never_becomes_ready(self):
        """Identical-looking untrusted records do not gain producer provenance."""
        smoke = smoke_fixture()
        quality = quality_fixture()
        result = bridge.compose(smoke, "a" * 40, quality)
        self.assertEqual(result["readiness"], "BLOCKED")
        self.assertEqual(result["checks"]["quality"]["status"], "BLOCKED")
        self.assertEqual(result["reported_local_observations"]["quality"],
                         "UNVERIFIED_CALLER_SUPPLIED_JSON")
        self.assertTrue(any("unauthenticated" in item for item in result["blockers"]))

    def test_bootstrap_excludes_source_only_composer(self):
        """Installer must not leak source-company demo helpers, tests or docs."""
        from bootstrap import SOURCE_INSTALLATION_EXCLUSIONS, copy_item
        excluded = (
            "scripts/phase1_mission_evidence.py",
            ".onecompany/selftest/test_phase1_mission_evidence.py",
            "docs/PHASE1-MISSION-EVIDENCE.md",
        )
        for relative in excluded:
            self.assertIn(relative, SOURCE_INSTALLATION_EXCLUSIONS)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for relative in excluded:
                copy_item(ROOT / relative, target / relative, False, target)
                self.assertFalse((target / relative).exists())

    def test_reject_forged_smoke_scope_authority_and_mismatched_refs(self):
        """No stale or invented fixture proof can become a positive dashboard."""
        cases = [
            ("schema", "bogus"),
            ("status", "DEPLOYED"),
            ("owner_implementation_approved", True),
            ("run_key", "forged-key"),
            ("lease_id", "forged-lease"),
            ("canonical_work_unit", "forged"),
            ("deployable", True),
            ("requested_extra_spend", 1),
            ("source_refs_unverified", {"head": "b" * 40, "base": "a" * 40}),
            ("real_local_http", {"status": "PASS", "health": "PASS", "fixture_discarded": False}),
            ("planning", {"mode": "READ_ONLY_PROPOSAL", "authorization": "GRANTED"}),
        ]
        for key, value in cases:
            with self.subTest(key=key):
                sample = smoke_fixture()
                sample[key] = value
                with self.assertRaises(ValueError):
                    bridge.compose(sample, "a" * 40, quality_fixture())

    def test_reject_wrong_quality_revision_or_fake_scope(self):
        """Only actual local quality PASS for the same caller revision is accepted."""
        for key, value in [
            ("revision", "b" * 40), ("status", "PENDING"),
            ("scope", "remote_cloud"), ("deployable", True), ("schema", "unknown"),
        ]:
            with self.subTest(key=key):
                quality = quality_fixture()
                quality[key] = value
                with self.assertRaisesRegex(ValueError, "QUALITY_EVIDENCE"):
                    bridge.compose(smoke_fixture(), "a" * 40, quality)

    def test_canonical_journey_combines_without_authority_or_stale_preview(self):
        """Preserve real onboarding project/steps while keeping evidence blockers."""
        project = copy.deepcopy(smoke_fixture()["project"])
        journey = {
            "schema": "onecompany.first-run-journey.v1",
            "read_only": True, "approval": "NOT_GRANTED",
            "project": project, "stage": "PROPOSAL_READY_NOT_APPROVED",
            "steps": [{"title": "Edit Product Brief", "status": "complete_draft_not_approved"}],
            "blockers": [], "next_action": "Review plan", "run_key": None,
        }
        result = bridge.compose(smoke_fixture(), "a" * 40, quality_fixture(), journey)
        self.assertEqual(result["schema"], "onecompany.mission-control-dashboard.phase1.v1")
        self.assertEqual(result["project"], project)
        self.assertFalse(result["authority_granted"])
        self.assertNotIn("preview_url", result)
        self.assertIn("Edit Product Brief", render(result).decode())
        self.assertTrue(any("No owner approval" in item for item in result["blockers"]))
        for key, value in [("approval", "GRANTED"), ("project", {"name": "other"})]:
            invalid = dict(journey, **{key: value})
            with self.assertRaises(ValueError):
                bridge.compose(smoke_fixture(), "a" * 40, quality_fixture(), invalid)

    @unittest.skipUnless(os.name == "posix", "nofollow regular-file assertion is POSIX-specific")
    def test_read_object_and_cli_bounds_are_real(self):
        """CLI emits consumable JSON and refuses symlink, oversized or list inputs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smoke = root / "smoke.json"
            quality = root / "quality.json"
            smoke.write_text(json.dumps(smoke_fixture()), encoding="utf-8")
            quality.write_text(json.dumps(quality_fixture()), encoding="utf-8")
            cmd = [sys.executable, str(HELPER), "--smoke", str(smoke),
                   "--quality", str(quality), "--revision", "a" * 40]
            run = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=12)
            self.assertEqual(run.returncode, 0, run.stderr)
            output = json.loads(run.stdout)
            self.assertEqual(output["checks"]["quality"]["status"], "BLOCKED")
            self.assertFalse(output["authority_granted"])
            link = root / "linked.json"
            link.symlink_to(smoke)
            with self.assertRaises(OSError):
                bridge.read_object(link)
            smoke.write_text("x" * (bridge.MAX_INPUT_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "EVIDENCE_TOO_LARGE"):
                bridge.read_object(smoke)
            smoke.write_text("[]")
            with self.assertRaisesRegex(ValueError, "EVIDENCE_OBJECT_REQUIRED"):
                bridge.read_object(smoke)
            bad = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=12)
            self.assertEqual(bad.returncode, 2)
            self.assertIn("BLOCKED:", bad.stderr)


if __name__ == "__main__":
    unittest.main()
