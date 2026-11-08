import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import fixture_check as fc  # noqa: E402


def fx(fid, kind="running-app", status=200, digest="a", **over):
    item = {"id": fid, "kind": kind, "revision": "1" * 40, "command": "npm start",
            "probe": {"method": "GET", "path": "/health", "status": status, "response_sha256": digest * 64}}
    item.update(over)
    return item


class FixtureCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, body):
        path = self.tmp / "f.json"
        path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
        return path

    def cli(self, path):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "fixture_check.py"), str(path)],
                              capture_output=True, text=True)

    def test_genuine_fixtures_pass(self):
        p = self.write({"fixtures": [fx("a", digest="a"), fx("b", digest="b")]})
        result = fc.classify(fc.load_fixtures(p))
        self.assertEqual(result["genuine"], ["a", "b"])
        self.assertEqual(fc.exit_code(result), 0)
        self.assertEqual(self.cli(p).returncode, 0)

    def test_non_running_kinds_are_not_genuine(self):
        for kind in ("mock", "stub", "recorded", "in-process", "Running-App"):
            p = self.write({"fixtures": [fx("a", kind=kind)]})
            result = fc.classify(fc.load_fixtures(p))
            self.assertEqual(result["not_genuine"], ["a"], kind)
            self.assertEqual(self.cli(p).returncode, 1, kind)

    def test_server_error_probe_is_unhealthy(self):
        p = self.write({"fixtures": [fx("a", status=503)]})
        self.assertEqual(fc.classify(fc.load_fixtures(p))["unhealthy"], ["a"])
        self.assertEqual(self.cli(p).returncode, 1)

    def test_shared_response_hash_is_copied_evidence(self):
        p = self.write({"fixtures": [fx("a"), fx("b")]})
        result = fc.classify(fc.load_fixtures(p))
        self.assertEqual(result["duplicate_evidence"], ["a", "b"])
        self.assertEqual(result["genuine"], [])
        self.assertEqual(self.cli(p).returncode, 1)

    def test_malformed_input_is_unable_to_verify(self):
        bad = [
            "not json", {"fixtures": []}, {"fixtures": [fx("a"), fx("a", digest="b")]},
            {"fixtures": [fx("a", revision="abc")]}, {"fixtures": [fx("a", command=" ")]},
            {"fixtures": [fx("a", status=True)]}, {"fixtures": [fx("a", status=99)]},
            {"fixtures": [fx("a", digest="z")]}, {"fixtures": [fx("a", probe=None)]},
            {"fixtures": [fx("a", probe={"method": "GET", "path": "health", "status": 200, "response_sha256": "a" * 64})]},
            {"fixtures": ["x"]},
            {"fixtures": [fx("a", probe={"method": "GET", "path": "/h", "status": 200, "response_sha256": "a" * 64 + "\n"})]},
            {"fixtures": [fx("a", revision="1" * 40 + "\n")]},
        ]
        for body in bad:
            r = self.cli(self.write(body))
            self.assertEqual(r.returncode, 2, body)
            self.assertIn("UNABLE TO VERIFY", r.stderr)
        self.assertEqual(self.cli(self.tmp / "missing.json").returncode, 2)


if __name__ == "__main__":
    unittest.main()
