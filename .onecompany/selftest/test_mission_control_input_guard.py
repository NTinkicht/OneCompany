"""Source-only Mission Control input hardening and actual loopback smoke."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "mission_control_local.py"
sys.path.insert(0, str(ROOT / "scripts"))
from mission_control_projection import project

spec = importlib.util.spec_from_file_location("mission_control_input_guard", SCRIPT)
mission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mission)


def canonical() -> dict:
    revision = "a" * 40
    return project(
        revision, {"status": "DRAFT", "approved": False},
        {"bounded": True},
        {name: {"revision": revision, "status": "PASS"}
         for name in ("app", "quality", "preview")},
    )


class MissionInputGuardTests(unittest.TestCase):
    def write(self, folder: Path, name: str, value: dict) -> Path:
        path = folder / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_real_canonical_projection_served_on_loopback(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            path = self.write(folder, "projection.json", canonical())
            before = path.read_bytes()
            child = subprocess.Popen(
                [sys.executable, str(SCRIPT), "--input", str(path), "--port", "0"],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            try:
                ready, _, _ = select.select([child.stdout], [], [], 10)
                self.assertTrue(ready, "local server did not announce loopback URL")
                line = child.stdout.readline().strip()
                self.assertTrue(line.startswith("Mission Control: http://127.0.0.1:"),
                                line + child.stderr.read() if child.poll() is not None else line)
                address = line.split("Mission Control: ", 1)[1]
                with urllib.request.urlopen(address, timeout=3) as response:
                    body = response.read().decode("utf-8")
                    self.assertEqual(response.status, 200)
                    self.assertIn("id='status'>READY</p>", body)
                    self.assertIn("No execution or deployment authority", body)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(sorted(p.name for p in folder.iterdir()),
                                 ["projection.json"])
            finally:
                child.terminate()
                try:
                    child.communicate(timeout=4)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.communicate(timeout=4)

    def test_wrong_schema_and_authority_state_refused_before_server(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            for name, mutation in (
                ("schema", lambda d: d.update(schema="invented")),
                ("authority", lambda d: d.update(authority_granted=True)),
                ("missing authority", lambda d: d.pop("authority_granted")),
                ("wrong revision", lambda d: d.update(revision="not-a-sha")),
                ("missing check", lambda d: d["checks"].pop("quality")),
                ("forged check", lambda d: d["checks"]["app"].update(status="SUCCESS")),
                ("false-like check", lambda d: d["checks"]["app"].update(exact_revision=1)),
            ):
                with self.subTest(name=name):
                    candidate = canonical()
                    mutation(candidate)
                    path = self.write(folder, "candidate.json", candidate)
                    with mock.patch.object(mission, "serve",
                                           side_effect=AssertionError("must not serve")):
                        self.assertEqual(mission.main(
                            ["--input", str(path), "--port", "0"]), 2)

    def test_invalid_ports_refuse_before_socket_setup(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write(Path(td), "projection.json", canonical())
            for port in ("-1", "65536", "999999999"):
                with self.subTest(port=port), \
                     mock.patch.object(mission, "serve",
                                       side_effect=AssertionError("must not bind")):
                    self.assertEqual(mission.main(
                        ["--input", str(path), "--port", port]), 2)

    def test_duplicate_key_nan_and_deep_json_refused(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            path = folder / "input.json"
            for raw in (
                '{"schema":"a","schema":"b"}',
                '{"nonfinite":NaN}',
                '{"nonfinite":1e9999}',
                '{"nonfinite":-1e9999}',
                '{"outer":' * 1100 + "null" + "}" * 1100,
                '[]',
            ):
                with self.subTest(raw=raw[:32]):
                    path.write_text(raw, encoding="utf-8")
                    with mock.patch.object(mission, "serve",
                                           side_effect=AssertionError("must not serve")):
                        self.assertEqual(mission.main(
                            ["--input", str(path), "--port", "0"]), 2)

    @unittest.skipUnless(os.name == "posix", "POSIX anchored reader required")
    def test_symlink_parent_leaf_fifo_and_oversize_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            target = self.write(folder, "valid.json", canonical())
            leaf = folder / "link.json"
            leaf.symlink_to(target)
            with self.assertRaises(OSError):
                mission._read_projection_file(leaf)
            parent = folder / "parent-link"
            parent.symlink_to(folder, target_is_directory=True)
            with self.assertRaises(OSError):
                mission._read_projection_file(parent / "valid.json")
            fifo = folder / "pipe.json"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "REGULAR_INPUT_REQUIRED"):
                mission._read_projection_file(fifo)
            large = folder / "large.json"
            large.write_bytes(b"{" + b" " * mission.MAX_PROJECTION_BYTES + b"}")
            with self.assertRaisesRegex(ValueError, "TOO_LARGE"):
                mission._read_projection_file(large)
            self.assertEqual(json.loads(target.read_text()), canonical())

    def test_missing_secure_flags_refuse_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write(Path(td), "valid.json", canonical())
            for flag in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"):
                with self.subTest(flag=flag):
                    with mock.patch.object(mission.os, flag, 0):
                        with self.assertRaisesRegex(ValueError, "SECURE_READ_UNAVAILABLE"):
                            mission._read_projection_file(path)

    def test_optional_journey_cannot_claim_approval(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            path = self.write(folder, "projection.json", canonical())
            invalid_journey = self.write(folder, "journey.json", {
                "schema": "onecompany.first-run-journey.v1",
                "read_only": True, "approval": "GRANTED",
            })
            with mock.patch.object(mission, "serve",
                                   side_effect=AssertionError("must not serve")):
                self.assertEqual(mission.main([
                    "--input", str(path), "--journey", str(invalid_journey),
                    "--port", "0"]), 2)


if __name__ == "__main__":
    unittest.main()
