"""Fail-closed regression for the trusted external Mistral wrapper/implementation stage.

Reproduces the 2026-10-10 EXTERNAL_REVIEW_LIMIT_PATCH_MISMATCH failure
without invoking model inference, GitHub, or credentials.
"""
from __future__ import annotations

from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/onecompany-mistral-external-review.yml"
WRAPPER = ROOT / "scripts/mistral_external_review.py"
IMPLEMENTATION = ROOT / ".github/mistral_external_review_impl.py"
STAGE = "/tmp/onecompany-external-review-trusted"
LIMITS = {
    "MAX_DIFF_BYTES = 48_000": "MAX_DIFF_BYTES = 256_000",
    "MAX_PROMPT_BYTES = 64_000": "MAX_PROMPT_BYTES = 320_000",
}


def bounded_limit_patch(source: str) -> str:
    for old, new in LIMITS.items():
        if source.count(old) != 1:
            raise ValueError("EXTERNAL_REVIEW_LIMIT_PATCH_MISMATCH")
        source = source.replace(old, new)
    return source


class ExternalMistralBootstrapTests(unittest.TestCase):
    def test_trusted_wrapper_stage_preserves_relative_import_and_all_calls(self):
        if not WORKFLOW.is_file():
            self.skipTest("external workflow not installed on disposable bootstrap")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            STAGE + "/scripts/mistral_external_review.py", workflow
        )
        self.assertIn(
            STAGE + "/.github/mistral_external_review_impl.py", workflow
        )
        self.assertIn(
            "install -m 600 scripts/mistral_external_review.py", workflow
        )
        self.assertIn(
            "install -m 600 .github/mistral_external_review_impl.py", workflow
        )
        self.assertNotIn("/tmp/onecompany-mistral-external-review.py", workflow)
        self.assertEqual(
            workflow.count(STAGE + "/scripts/mistral_external_review.py"), 8
        )
        self.assertIn("if text.count(old) != 1:", workflow)
        self.assertIn("python -I", workflow)

    def test_runtime_limit_patch_targets_actual_implementation_only(self):
        source = IMPLEMENTATION.read_text(encoding="utf-8")
        self.assertNotIn("MAX_DIFF_BYTES = 48_000", WRAPPER.read_text(encoding="utf-8"))
        result = bounded_limit_patch(source)
        for old, new in LIMITS.items():
            self.assertNotIn(old, result)
            self.assertEqual(result.count(new), 1)
        with self.assertRaisesRegex(ValueError, "LIMIT_PATCH_MISMATCH"):
            bounded_limit_patch(result)
        with self.assertRaisesRegex(ValueError, "LIMIT_PATCH_MISMATCH"):
            bounded_limit_patch(source.replace("MAX_DIFF_BYTES = 48_000", ""))

    def test_staged_wrapped_import_runs_without_github_or_model_access(self):
        if not WRAPPER.is_file() or not IMPLEMENTATION.is_file():
            self.skipTest("reviewer not installed on disposable bootstrap")
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            (stage / "scripts").mkdir()
            (stage / ".github").mkdir()
            staged_wrapper = stage / "scripts/mistral_external_review.py"
            staged_impl = stage / ".github/mistral_external_review_impl.py"
            staged_wrapper.write_bytes(WRAPPER.read_bytes())
            staged_impl.write_text(
                bounded_limit_patch(IMPLEMENTATION.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
            # __bootstrap_only__ avoids calling main(); only prove the
            # wrapper can import the actual staged implementation in -I mode.
            program = (
                "import runpy, sys; "
                "runpy.run_path(sys.argv[1], run_name='__bootstrap_only__')"
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-c", program, str(staged_wrapper)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr[:500])


if __name__ == "__main__":
    unittest.main()
