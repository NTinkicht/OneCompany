#!/usr/bin/env python3
"""Regression coverage for unattended L5 external review dispatch under python -I."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "scripts" / "mistral_external_dispatch.py"


class ExternalDispatchIsolationTests(unittest.TestCase):
    def _invoke(self, script: Path, *, pythonpath: str | None = None):
        env = dict(os.environ)
        # Fail before GitHub access. This proves the module loaded far enough
        # to reach the existing host-repository safety check.
        env["GITHUB_REPOSITORY"] = "untrusted/not-onecompany"
        env.pop("GH_TOKEN", None)
        if pythonpath is not None:
            env["PYTHONPATH"] = pythonpath
        return subprocess.run(
            [sys.executable, "-I", str(script), "prepare"],
            capture_output=True, text=True, env=env,
            timeout=25, check=False,
        )

    def test_isolated_dispatch_reaches_existing_host_guard(self):
        result = self._invoke(DISPATCH)
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WRONG_HOST_REPOSITORY", combined)
        self.assertNotIn("ModuleNotFoundError", combined)

    def test_pythonpath_shadow_does_not_replace_trusted_sibling(self):
        with tempfile.TemporaryDirectory() as temp:
            shadow = Path(temp) / "mistral_external_review.py"
            marker = Path(temp) / "shadow_was_imported"
            shadow.write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
                "raise RuntimeError('UNTRUSTED_SHADOW_IMPORTED')\n",
                encoding="utf-8",
            )
            result = self._invoke(DISPATCH, pythonpath=temp)
            combined = result.stdout + result.stderr
            self.assertIn("WRONG_HOST_REPOSITORY", combined)
            self.assertNotIn("UNTRUSTED_SHADOW_IMPORTED", combined)
            self.assertFalse(marker.exists())

    def test_missing_sibling_fails_closed_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            isolated = Path(temp) / "mistral_external_dispatch.py"
            shutil.copyfile(DISPATCH, isolated)
            result = self._invoke(isolated)
            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("EXTERNAL_DISPATCH_REVIEW_SOURCE_INVALID", combined)
            self.assertNotIn("WRONG_HOST_REPOSITORY", combined)


if __name__ == "__main__":
    unittest.main()
