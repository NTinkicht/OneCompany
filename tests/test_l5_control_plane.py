#!/usr/bin/env python3
"""Hermetic tests for the shared L5 control-plane execution-mode policy."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import l5_control_plane as cp  # noqa: E402


class ControlPlaneTests(unittest.TestCase):
    """Prove reversible LIVE_SAFE writes and fail-closed ACTIVE binding."""

    def manifest(self, **overrides):
        value = {
            "schema_version": "1.0",
            "control_repository": "NTinkicht/OneCompany",
            "control_ref": "a" * 40,
            "execution_mode": "LIVE_SAFE",
            "platform_enforcement": "DEFERRED_FOR_VALIDATION",
            "mutation_allowed": True,
            "managed_repositories": [
                "NTinkicht/OneCompany",
                "NTinkicht/Tabibi",
                "NTinkicht/veritas-atlas",
            ],
            "activation_requirements": sorted(cp.REQUIRED_ACTIVATION),
        }
        value.update(overrides)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "control-plane.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_live_safe_allows_reversible_operations(self):
        path = self.manifest()
        for operation in (
            "retry_ci",
            "dispatch_review",
            "remediate_review",
            "update_branch",
            "reserve_next_wu",
        ):
            self.assertEqual(cp.mutation_policy(operation, path), (True, "CONTROL_PLANE_LIVE_SAFE"))

    def test_live_safe_blocks_main_changing_operations(self):
        path = self.manifest()
        for operation in ("merge_expected_head", "revert"):
            self.assertEqual(
                cp.mutation_policy(operation, path),
                (False, "CONTROL_PLANE_LIVE_SAFE_MAIN_CHANGE_BLOCKED"),
            )

    def test_shadow_fails_closed(self):
        path = self.manifest(execution_mode="SHADOW", mutation_allowed=False)
        self.assertEqual(cp.mutation_policy("retry_ci", path), (False, "CONTROL_PLANE_SHADOW"))

    def test_active_requires_pinned_ref_complete_evidence_and_runtime_binding(self):
        base = {
            "execution_mode": "ACTIVE",
            "platform_enforcement": "VERIFIED",
            "mutation_allowed": True,
        }
        missing = self.manifest(**base)
        self.assertEqual(cp.mutation_policy("merge_expected_head", missing)[1], "ACTIVATION_EVIDENCE_MISSING")

        unpinned = self.manifest(
            **base,
            control_ref="main",
            activation_evidence={name: True for name in cp.REQUIRED_ACTIVATION},
        )
        self.assertEqual(cp.mutation_policy("merge_expected_head", unpinned)[1], "CONTROL_PLANE_REF_NOT_PINNED")

        complete = self.manifest(
            **base,
            activation_evidence={name: True for name in cp.REQUIRED_ACTIVATION},
        )
        with mock.patch.object(
            cp,
            "_runtime_source_verified",
            return_value=(False, "CONTROL_PLANE_RUNTIME_SOURCE_MISMATCH"),
        ):
            self.assertEqual(
                cp.mutation_policy("merge_expected_head", complete),
                (False, "CONTROL_PLANE_RUNTIME_SOURCE_MISMATCH"),
            )
        with mock.patch.object(
            cp,
            "_runtime_source_verified",
            return_value=(True, "CONTROL_PLANE_RUNTIME_SOURCE_VERIFIED"),
        ):
            self.assertEqual(
                cp.mutation_policy("merge_expected_head", complete),
                (True, "CONTROL_PLANE_ACTIVE"),
            )

    def test_runtime_binding_ignores_candidate_local_blob_map(self):
        certified = {
            ".l5/trust-policy.json": "1" * 40,
            "scripts/l5_control_plane.py": "2" * 40,
            "scripts/l5_trust_boundary.py": "3" * 40,
            "scripts/l5_activation.py": "4" * 40,
            "scripts/l5_recovery.py": "5" * 40,
            "scripts/l5_state_machine.py": "6" * 40,
            "scripts/l5_write_adapter.py": "7" * 40,
        }
        value = {
            "control_ref": "a" * 40,
            # Deliberately bogus candidate-local data: it must not be authority.
            "runtime_file_git_blob_sha": {name: "f" * 40 for name in certified},
        }
        with mock.patch.object(
            cp,
            "_certified_runtime_blob_map",
            return_value=(certified, "CONTROL_PLANE_CERTIFIED_RUNTIME_RESOLVED"),
        ) as certified_lookup, mock.patch.object(
            cp,
            "_local_runtime_blob_map",
            return_value=(dict(certified), "CONTROL_PLANE_RUNTIME_SOURCE_RESOLVED"),
        ):
            self.assertEqual(
                cp._runtime_source_verified(value),
                (True, "CONTROL_PLANE_RUNTIME_SOURCE_VERIFIED"),
            )
            certified_lookup.assert_called_once_with("a" * 40)

    def test_runtime_file_set_and_blob_drift_fail_closed(self):
        certified = {
            ".l5/trust-policy.json": "1" * 40,
            "scripts/l5_control_plane.py": "2" * 40,
            "scripts/l5_trust_boundary.py": "3" * 40,
            "scripts/l5_activation.py": "4" * 40,
            "scripts/l5_recovery.py": "5" * 40,
            "scripts/l5_state_machine.py": "6" * 40,
            "scripts/l5_write_adapter.py": "7" * 40,
        }
        value = {"control_ref": "a" * 40}
        extra = {**certified, "scripts/l5_unreviewed.py": "8" * 40}
        with mock.patch.object(
            cp,
            "_certified_runtime_blob_map",
            return_value=(certified, "CONTROL_PLANE_CERTIFIED_RUNTIME_RESOLVED"),
        ), mock.patch.object(
            cp,
            "_local_runtime_blob_map",
            return_value=(extra, "CONTROL_PLANE_RUNTIME_SOURCE_RESOLVED"),
        ):
            self.assertEqual(
                cp._runtime_source_verified(value),
                (False, "CONTROL_PLANE_RUNTIME_FILE_SET_MISMATCH"),
            )

        changed = dict(certified)
        changed["scripts/l5_write_adapter.py"] = "9" * 40
        with mock.patch.object(
            cp,
            "_certified_runtime_blob_map",
            return_value=(certified, "CONTROL_PLANE_CERTIFIED_RUNTIME_RESOLVED"),
        ), mock.patch.object(
            cp,
            "_local_runtime_blob_map",
            return_value=(changed, "CONTROL_PLANE_RUNTIME_SOURCE_RESOLVED"),
        ):
            self.assertEqual(
                cp._runtime_source_verified(value),
                (False, "CONTROL_PLANE_RUNTIME_SOURCE_MISMATCH"),
            )

    def test_required_mutation_runtime_contains_transitive_planner_and_actuator(self):
        for path in (
            "scripts/l5_recovery.py",
            "scripts/l5_state_machine.py",
            "scripts/l5_write_adapter.py",
        ):
            self.assertIn(path, cp.REQUIRED_MUTATION_RUNTIME_FILES)

    def test_missing_or_malformed_manifest_fails_closed(self):
        missing = Path(tempfile.gettempdir()) / "missing-onecompany-control-plane.json"
        missing.unlink(missing_ok=True)
        self.assertEqual(cp.mutation_policy("retry_ci", missing)[1], "CONTROL_PLANE_UNAVAILABLE")

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        malformed = Path(directory.name) / "bad.json"
        malformed.write_text("{bad", encoding="utf-8")
        self.assertEqual(cp.mutation_policy("retry_ci", malformed)[1], "CONTROL_PLANE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
