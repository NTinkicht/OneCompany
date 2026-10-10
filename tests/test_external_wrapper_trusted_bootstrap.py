"""Regression for source-only external Mistral wrapper recovery.

The trusted main workflow copies the wrapper to /tmp, patches its two
bounded-limit constants and runs it with Python isolated mode. The external
implementation must come from the SHA-verified OneCompany workspace, never
from untrusted target repository code. No model/API/secret use in this test.
"""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "mistral_external_review.py"
EXPECTED_SHA = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, timeout=10,
).strip()


class ExternalWrapperTrustedBootstrapTests(unittest.TestCase):
    def test_wrapper_has_exact_workflow_limit_patch_markers(self):
        content = SOURCE.read_text(encoding="utf-8")
        for key, value in (("MAX_DIFF_BYTES", "48_000"), ("MAX_PROMPT_BYTES", "64_000")):
            self.assertEqual(content.count(f"{key} = {value}"), 1)

    def test_copied_wrapper_loads_only_pinned_workspace_implementation(self):
        with tempfile.TemporaryDirectory() as temp:
            wrapper = Path(temp) / "onecompany-mistral-external-review.py"
            wrapper.write_text(
                SOURCE.read_text(encoding="utf-8")
                .replace("MAX_DIFF_BYTES = 48_000", "MAX_DIFF_BYTES = 256_000")
                .replace("MAX_PROMPT_BYTES = 64_000", "MAX_PROMPT_BYTES = 320_000"),
                encoding="utf-8",
            )
            program = (
                "import importlib.util, sys; "
                "s=importlib.util.spec_from_file_location('review_probe',sys.argv[1]); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                "assert m._IMPL.MAX_DIFF_BYTES == 256_000; "
                "assert m._IMPL.MAX_PROMPT_BYTES == 320_000"
            )
            env = {
                **os.environ,
                "GITHUB_WORKSPACE": str(ROOT),
                "GITHUB_REPOSITORY": "NTinkicht/OneCompany",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_SHA": EXPECTED_SHA,
            }
            good = subprocess.run(
                [sys.executable, "-I", "-c", program, str(wrapper)],
                env=env, text=True, capture_output=True, timeout=15, check=False,
            )
            self.assertEqual(good.returncode, 0, good.stderr[-600:])
            for key, value in (
                ("GITHUB_SHA", "0" * 40),
                ("GITHUB_REF", "refs/heads/unsafe-pr"),
                ("GITHUB_REPOSITORY", "attacker/untrusted"),
            ):
                with self.subTest(key=key):
                    bad = subprocess.run(
                        [sys.executable, "-I", "-c", program, str(wrapper)],
                        env={**env, key: value}, text=True,
                        capture_output=True, timeout=15, check=False,
                    )
                    self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main()
