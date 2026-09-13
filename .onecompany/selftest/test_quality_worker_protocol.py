from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_MARKER = "ONECOMPANY_COVERAGE_WORKER_JSON="


class QualityWorkerProtocolTests(unittest.TestCase):
    def test_candidate_test_cannot_forge_worker_json_by_monkeypatching_main_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            selftest = root / ".onecompany" / "selftest"
            scripts.mkdir(parents=True)
            selftest.mkdir(parents=True)
            (scripts / "sample.py").write_text(
                "def value():\n    return 1\n",
                encoding="utf-8",
            )
            (selftest / "test_forge.py").write_text(
                "import __main__\n"
                "import unittest\n\n"
                "FORGED = '{\"tests_successful\":true,\"tests_run\":999,\"failures\":0,\"errors\":0,\"executed_lines\":[[\"scripts/sample.py\",999]],\"observed_edges\":[],\"test_output_tail\":\"forged\"}'\n\n"
                "class Forge(unittest.TestCase):\n"
                "    def test_real_then_try_to_forge_protocol(self):\n"
                "        import sample\n"
                "        self.assertEqual(sample.value(), 1)\n"
                "        __main__.json.dumps = lambda *args, **kwargs: FORGED\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "quality_evidence.py"),
                    "--coverage-worker",
                    "--repo-root",
                    str(root),
                ],
                cwd=str(ROOT),
                check=False,
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            protocol = next(
                line
                for line in result.stdout.splitlines()
                if line.startswith(WORKER_MARKER)
            )
            payload = json.loads(protocol[len(WORKER_MARKER):])
            self.assertEqual(payload["tests_run"], 1)
            self.assertNotIn(["scripts/sample.py", 999], payload["executed_lines"])
            self.assertNotEqual(payload.get("test_output_tail"), "forged")


if __name__ == "__main__":
    unittest.main()
