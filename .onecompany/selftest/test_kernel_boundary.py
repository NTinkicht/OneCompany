from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import kernel_boundary


class KernelBoundaryTests(unittest.TestCase):
    def test_repository_kernel_boundary_is_clean(self):
        errors = kernel_boundary.boundary_errors()
        self.assertEqual(errors, [])

    def test_userspace_import_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "kernel.py").write_text("import company.domain\n", encoding="utf-8")
            policy = root / "policy.json"
            policy.write_text(
                '{"trusted_modules":["kernel"],"forbidden_repo_import_roots":["company"]}',
                encoding="utf-8",
            )
            errors = kernel_boundary.boundary_errors(policy, scripts)
        self.assertTrue(any("forbidden userspace root company" in error for error in errors), errors)

    def test_unlisted_local_helper_import_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "kernel.py").write_text("import helper\n", encoding="utf-8")
            (scripts / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
            policy = root / "policy.json"
            policy.write_text(
                '{"trusted_modules":["kernel"],"forbidden_repo_import_roots":[]}',
                encoding="utf-8",
            )
            errors = kernel_boundary.boundary_errors(policy, scripts)
        self.assertTrue(any("unlisted local module helper" in error for error in errors), errors)

    def test_standard_library_import_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "kernel.py").write_text("import json\nfrom pathlib import Path\n", encoding="utf-8")
            policy = root / "policy.json"
            policy.write_text(
                '{"trusted_modules":["kernel"],"forbidden_repo_import_roots":[]}',
                encoding="utf-8",
            )
            errors = kernel_boundary.boundary_errors(policy, scripts)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
