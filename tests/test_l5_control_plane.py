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
    """Prove reversible LIVE_SAFE writes and main-change denial."""

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

        no_blobs = self.manifest(
            **base,
            activation_evidence={name: True for name in cp.REQUIRED_ACTIVATION},
        )
        self.assertEqual(
            cp.mutation_policy("merge_expected_head", no_blobs)[1],
            "CONTROL_PLANE_RUNTIME_BLOBS_MISSING",
        )

        complete = self.manifest(
            **base,
            activation_evidence={name: True for name in cp.REQUIRED_ACTIVATION},
            runtime_file_git_blob_sha={name: "b" * 40 for name in cp.PINNED_RUNTIME_FILES},
        )
        with mock.patch.object(cp, "_runtime_source_verified", return_value=(False, "CONTROL_PLANE_RUNTIME_SOURCE_MISMATCH")):
            self.assertEqual(
                cp.mutation_policy("merge_expected_head", complete),
                (False, "CONTROL_PLANE_RUNTIME_SOURCE_MISMATCH"),
            )
        with mock.patch.object(cp, "_runtime_source_verified", return_value=(True, "CONTROL_PLANE_RUNTIME_SOURCE_VERIFIED")):
            self.assertEqual(cp.mutation_policy("merge_expected_head", complete), (True, "CONTROL_PLANE_ACTIVE"))

    def test_runtime_blob_map_shape_fails_closed(self):
        self.assertEqual(
            cp._runtime_source_verified({"runtime_file_git_blob_sha": {}}),
            (False, "CONTROL_PLANE_RUNTIME_BLOBS_MISSING"),
        )
        malformed = {name: "z" * 40 for name in cp.PINNED_RUNTIME_FILES}
        self.assertEqual(
            cp._runtime_source_verified({"runtime_file_git_blob_sha": malformed}),
            (False, "CONTROL_PLANE_RUNTIME_BLOBS_INVALID"),
        )

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
