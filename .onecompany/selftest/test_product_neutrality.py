from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_product_neutrality.py"


class ProductNeutralityCheckTests(unittest.TestCase):
    def run_case(self, repository: str, with_client_evidence: bool) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="onecompany-neutrality-") as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            (root / "scripts" / SCRIPT.name).write_bytes(SCRIPT.read_bytes())
            if with_client_evidence:
                (root / "evidence").mkdir()
                (root / "evidence" / "project-observation.json").write_text("{}")
            env = dict(os.environ, GITHUB_REPOSITORY=repository)
            return subprocess.run(
                [sys.executable, str(root / "scripts" / SCRIPT.name)],
                env=env, text=True, capture_output=True, check=False,
            )

    def test_source_repository_rejects_client_evidence(self) -> None:
        result = self.run_case("NTinkicht/OneCompany", True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_source_repository_without_evidence_passes(self) -> None:
        result = self.run_case("NTinkicht/OneCompany", False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_target_repository_can_own_runtime_evidence(self) -> None:
        result = self.run_case("example/unrelated-project", True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
