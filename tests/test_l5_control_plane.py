#!/usr/bin/env python3
"""Hermetic tests for the shared L5 control-plane execution-mode policy."""
from __future__ import annotations

import json
import os
import subprocess
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

    def certified_runtime(self) -> tuple[tempfile.TemporaryDirectory, Path, str]:
        """Create a real Git object store containing a complete L5 runtime."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / ".l5").mkdir(parents=True)
        (root / "scripts").mkdir(parents=True)
        paths = set(cp.REQUIRED_MUTATION_RUNTIME_FILES) | {
            "scripts/l5_kernel.py",
            "scripts/l5_ledger.py",
            "scripts/l5_shadow.py",
        }
        for relative in sorted(paths):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# certified {relative}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "l5-test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "L5 Test"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "certified runtime"], cwd=root, check=True)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        self.assertRegex(sha, r"^[0-9a-f]{40}$")
        return directory, root, sha

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

    def test_runtime_binding_is_derived_from_control_ref_not_candidate_map(self):
        _directory, root, control_ref = self.certified_runtime()
        value = {
            "control_ref": control_ref,
            # Deliberately bogus candidate-local data. Production verification
            # must ignore it and derive identities from the pinned Git tree.
            "runtime_file_git_blob_sha": {"scripts/l5_control_plane.py": "f" * 40},
        }
        with mock.patch.object(cp, "ROOT", root), mock.patch.dict(
            os.environ, {"L5_CONTROL_REPOSITORY_ROOT": str(root)}, clear=False
        ):
            self.assertEqual(
                cp._runtime_source_verified(value),
                (True, "CONTROL_PLANE_RUNTIME_SOURCE_VERIFIED"),
            )

            # Mutating a transitive actuator dependency after certification must
            # invalidate ACTIVE even though the manifest/control_ref is unchanged.
            (root / "scripts" / "l5_write_adapter.py").write_text(
                "# uncertified actuator change\n", encoding="utf-8"
            )
            self.assertEqual(
                cp._runtime_source_verified(value),
                (False, "CONTROL_PLANE_RUNTIME_SOURCE_MISMATCH"),
            )

    def test_runtime_namespace_addition_fails_closed(self):
        _directory, root, control_ref = self.certified_runtime()
        value = {"control_ref": control_ref}
        with mock.patch.object(cp, "ROOT", root), mock.patch.dict(
            os.environ, {"L5_CONTROL_REPOSITORY_ROOT": str(root)}, clear=False
        ):
            (root / "scripts" / "l5_unreviewed.py").write_text(
                "# not in certified tree\n", encoding="utf-8"
            )
            self.assertEqual(
                cp._runtime_source_verified(value),
                (False, "CONTROL_PLANE_RUNTIME_FILE_SET_MISMATCH"),
            )

    def test_runtime_read_failure_fails_closed(self):
        _directory, root, _control_ref = self.certified_runtime()
        with mock.patch.object(cp, "ROOT", root), mock.patch.object(
            Path, "read_bytes", side_effect=OSError("read failed")
        ):
            self.assertEqual(
                cp._local_runtime_blob_map(),
                (None, "CONTROL_PLANE_RUNTIME_SOURCE_UNAVAILABLE"),
            )

    def test_git_replace_and_repository_environment_cannot_redirect_control_ref(self):
        _directory, root, control_ref = self.certified_runtime()
        original_blob = subprocess.check_output(
            ["git", "rev-parse", f"{control_ref}:scripts/l5_write_adapter.py"],
            cwd=root,
            text=True,
        ).strip()
        (root / "scripts" / "l5_write_adapter.py").write_text(
            "# replacement commit actuator\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "scripts/l5_write_adapter.py"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "replacement runtime"], cwd=root, check=True)
        replacement = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        subprocess.run(["git", "replace", control_ref, replacement], cwd=root, check=True)

        hostile_env = {
            "L5_CONTROL_REPOSITORY_ROOT": str(root),
            "GIT_DIR": str(root / "not-the-repository"),
            "GIT_WORK_TREE": str(root / "elsewhere"),
            "GIT_OBJECT_DIRECTORY": str(root / "evil-objects"),
        }
        with mock.patch.object(cp, "ROOT", root), mock.patch.dict(os.environ, hostile_env, clear=False):
            blobs, reason = cp._certified_runtime_blob_map(control_ref)
            self.assertEqual(reason, "CONTROL_PLANE_CERTIFIED_RUNTIME_RESOLVED")
            self.assertEqual((blobs or {}).get("scripts/l5_write_adapter.py"), original_blob)
            self.assertEqual(
                cp._runtime_source_verified({"control_ref": control_ref}),
                (False, "CONTROL_PLANE_RUNTIME_SOURCE_MISMATCH"),
            )

    def test_l5_bytecode_artifacts_and_redirected_pycache_fail_closed(self):
        _directory, root, control_ref = self.certified_runtime()
        cache = root / "scripts" / "__pycache__"
        cache.mkdir()
        (cache / "l5_recovery.cpython-312.pyc").write_bytes(b"unchecked bytecode")
        with mock.patch.object(cp, "ROOT", root), mock.patch.dict(
            os.environ, {"L5_CONTROL_REPOSITORY_ROOT": str(root)}, clear=False
        ):
            self.assertEqual(
                cp._runtime_source_verified({"control_ref": control_ref}),
                (False, "CONTROL_PLANE_RUNTIME_BYTECODE_PRESENT"),
            )
            (cache / "l5_recovery.cpython-312.pyc").unlink()
            with mock.patch.object(cp.sys, "pycache_prefix", str(root / "external-cache")):
                self.assertEqual(
                    cp._runtime_source_verified({"control_ref": control_ref}),
                    (False, "CONTROL_PLANE_RUNTIME_PYCACHE_PREFIX_SET"),
                )

    def test_certified_ref_must_exist_and_include_mutation_closure(self):
        _directory, root, control_ref = self.certified_runtime()
        with mock.patch.dict(
            os.environ, {"L5_CONTROL_REPOSITORY_ROOT": str(root)}, clear=False
        ):
            blobs, reason = cp._certified_runtime_blob_map(control_ref)
            self.assertEqual(reason, "CONTROL_PLANE_CERTIFIED_RUNTIME_RESOLVED")
            self.assertIsNotNone(blobs)
            self.assertTrue(cp.REQUIRED_MUTATION_RUNTIME_FILES.issubset(blobs or {}))
            self.assertIn("scripts/l5_kernel.py", blobs or {})
            self.assertIn("scripts/l5_ledger.py", blobs or {})
            self.assertEqual(
                cp._certified_runtime_blob_map("f" * 40),
                (None, "CONTROL_PLANE_CERTIFIED_REF_UNAVAILABLE"),
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
