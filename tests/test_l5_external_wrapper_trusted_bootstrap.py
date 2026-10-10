"""Adversarial regression for the source-only external Mistral wrapper.

Required L5 hostile-controller CI discovers tests/test_l5_*.py. Model/target
worktree content must never replace implementation bytes from a pinned commit
during a privileged review safety/validation step. No model or API calls.
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
IMPLEMENTATION = ROOT / ".github" / "mistral_external_review_impl.py"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=15, check=True,
    )
    return result.stdout.strip()


class ExternalWrapperTrustedBootstrapTests(unittest.TestCase):
    def test_wrapper_has_exact_workflow_limit_patch_markers(self):
        content = SOURCE.read_text(encoding="utf-8")
        for key, value in (("MAX_DIFF_BYTES", "48_000"), ("MAX_PROMPT_BYTES", "64_000")):
            self.assertEqual(content.count(f"{key} = {value}"), 1)

    def test_copied_wrapper_imports_pinned_blob_not_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkout = root / "trusted-checkout"
            (checkout / ".github").mkdir(parents=True)
            (checkout / ".github/mistral_external_review_impl.py").write_bytes(
                IMPLEMENTATION.read_bytes()
            )
            git(checkout, "init", "-q")
            git(checkout, "add", ".github/mistral_external_review_impl.py")
            git(
                checkout, "-c", "user.name=Test", "-c",
                "user.email=test@example.invalid", "commit", "-qm", "pinned code",
            )
            sha = git(checkout, "rev-parse", "HEAD")
            wrapper = root / "onecompany-mistral-external-review.py"
            wrapper.write_text(
                SOURCE.read_text(encoding="utf-8")
                .replace("MAX_DIFF_BYTES = 48_000", "MAX_DIFF_BYTES = 256_000")
                .replace("MAX_PROMPT_BYTES = 64_000", "MAX_PROMPT_BYTES = 320_000"),
                encoding="utf-8",
            )
            program = (
                "import importlib.util,sys; "
                "s=importlib.util.spec_from_file_location('review_probe',sys.argv[1]); "
                "m=importlib.util.module_from_spec(s);s.loader.exec_module(m); "
                "assert m._IMPL.MAX_DIFF_BYTES==256_000; "
                "assert m._IMPL.MAX_PROMPT_BYTES==320_000"
            )
            env = {
                **os.environ,
                "GITHUB_WORKSPACE": str(checkout),
                "GITHUB_REPOSITORY": "NTinkicht/OneCompany",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_SHA": sha,
            }
            def execute(settings: dict[str, str]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-I", "-c", program, str(wrapper)],
                    env=settings, text=True, capture_output=True,
                    timeout=15, check=False,
                )

            self.assertEqual(execute(env).returncode, 0)
            # Attacker mutates the checked-out source after HEAD verification.
            # A mutable-path import would execute this hostile statement.
            (checkout / ".github/mistral_external_review_impl.py").write_text(
                "raise RuntimeError('DIRTY_WORKTREE_CODE_EXECUTED')\n",
                encoding="utf-8",
            )
            actual = execute(env)
            self.assertEqual(actual.returncode, 0, actual.stderr[-600:])

            for key, value in (
                ("GITHUB_SHA", "0" * 40),
                ("GITHUB_REF", "refs/heads/unsafe-pr"),
                ("GITHUB_REPOSITORY", "attacker/untrusted"),
            ):
                with self.subTest(key=key):
                    bad = execute({**env, key: value})
                    self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main()
