from __future__ import annotations

import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if not (ROOT / ".l5" / "control-plane.json").exists() or not (
    ROOT / ".l5" / "trust-policy.json"
).exists():
    raise unittest.SkipTest("source L5 control plane is not installed in this fresh target")


class BootstrapSourceLoaderTests(unittest.TestCase):
    """Prove hostile import artifacts cannot run before L5 attestation."""

    def _sandbox(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "scripts").mkdir(parents=True)
        (root / ".l5").mkdir(parents=True)
        shutil.copy2(ROOT / ".l5" / "control-plane.json", root / ".l5" / "control-plane.json")
        shutil.copy2(ROOT / ".l5" / "trust-policy.json", root / ".l5" / "trust-policy.json")
        shutil.copy2(ROOT / "scripts" / "control_plane_bootstrap.py", root / "scripts" / "control_plane_bootstrap.py")
        for source in (ROOT / "scripts").glob("l5_*.py"):
            shutil.copy2(source, root / "scripts" / source.name)
        return directory, root

    def _plant_hostile_unchecked_cache(self, root: Path, module: str) -> tuple[Path, Path]:
        marker = root / f"HOSTILE_{module.upper()}_EXECUTED"
        cache = root / "scripts" / "__pycache__"
        cache.mkdir(exist_ok=True)
        hostile = root / f"hostile_{module}.py"
        hostile.write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
            encoding="utf-8",
        )
        pyc = cache / f"{module}.{sys.implementation.cache_tag}.pyc"
        py_compile.compile(
            str(hostile),
            cfile=str(pyc),
            doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        )
        return marker, pyc

    def _entrypoint_env(self, root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "scripts")
        env["L5_CONTROL_PLANE_MANIFEST"] = str(root / ".l5" / "control-plane.json")
        return env

    def test_redirected_pycache_fails_closed_before_l5_import(self):
        _directory, root = self._sandbox()
        redirected = root / "redirected-cache"
        redirected.mkdir()
        env = self._entrypoint_env(root)
        env["PYTHONPYCACHEPREFIX"] = str(redirected)
        completed = subprocess.run(
            [sys.executable, "-c", "import control_plane_bootstrap as b; b.prepare_source_only_l5_imports()"],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("L5_BOOTSTRAP_PYCACHE_PREFIX_REDIRECTED", completed.stderr)

    def test_bootstrap_stdlib_imports_ignore_candidate_shadow_module(self):
        _directory, root = self._sandbox()
        marker = root / "HOSTILE_HASHLIB_EXECUTED"
        (root / "scripts" / "hashlib.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [sys.executable, "-c", "import control_plane_bootstrap"],
            cwd=root,
            env=self._entrypoint_env(root),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(marker.exists(), "candidate hashlib.py shadowed bootstrap stdlib import")

    def test_local_runtime_inventory_includes_shadow_packages(self):
        _directory, root = self._sandbox()
        package = root / "scripts" / "l5_kernel"
        package.mkdir()
        (package / "__init__.py").write_text("SHADOW = True\n", encoding="utf-8")
        code = (
            "import control_plane_bootstrap as b\n"
            "b.prepare_source_only_l5_imports()\n"
            "runtime = b._local_runtime(b.ROOT)\n"
            "assert 'scripts/l5_kernel/__init__.py' in runtime, runtime\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root,
            env=self._entrypoint_env(root),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_all_local_python_bytecode_is_removed(self):
        _directory, root = self._sandbox()
        marker, pyc = self._plant_hostile_unchecked_cache(root, "unrelated_shadow")
        code = (
            "import control_plane_bootstrap as b\n"
            "b.prepare_source_only_l5_imports()\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root,
            env=self._entrypoint_env(root),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(pyc.exists())
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
