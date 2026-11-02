"""WU-P1-E2E-001 (#153): fresh-user idea-to-running-app acceptance journey.

Drives the real CLI as subprocesses, in order: saved owner brief -> approve-brief
(preview, then explicit owner ack) -> runtime-bind (real loopback app) ->
postbind-assure (per-criterion evidence). Negative cases prove that stale or
absent evidence can never read as ready/covered and that no lease is granted.
No network beyond loopback, no provider, no credentials.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "onecompany.py"
APP_PATH = ROOT / "examples" / "vertical-slice" / "app.py"
sys.path.insert(0, str(ROOT / "scripts"))
import postbind_assurance as pa  # noqa: E402

WU, RK = "WU-E2E-001", "run/e2e-1"
ANSWERS = ("--audience", "Families", "--problem", "Keep track of small tasks",
           "--outcome", "See a local checklist", "--first-feature", "Add and finish a checklist item")
EXISTING = {"README.md": "# Existing project\n", "tests/test_existing.py": "def test_ok():\n    assert True\n"}
PRESERVED = list(EXISTING) + ["examples/vertical-slice/app.py"]


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, timeout=120)


def git(ws: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(ws), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


def digests(ws: Path, names) -> dict:
    return {n: hashlib.sha256((ws / n).read_bytes()).hexdigest() for n in names}


@unittest.skipUnless(APP_PATH.is_file(), "source-only disposable demo not installed")
class IdeaToRunningJourneyTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = Path(self._t.name)
        self.ws = self.tmp / "proj"
        (self.ws / "examples" / "vertical-slice").mkdir(parents=True)
        shutil.copy(APP_PATH, self.ws / "examples" / "vertical-slice" / "app.py")
        for name, text in EXISTING.items():
            (self.ws / name).parent.mkdir(parents=True, exist_ok=True)
            (self.ws / name).write_text(text)
        git(self.ws, "init", "-q")
        git(self.ws, "add", "-A"); git(self.ws, "commit", "-q", "-m", "base")
        self.base = git(self.ws, "rev-parse", "HEAD")
        (self.ws / "feature.txt").write_text("x")
        git(self.ws, "add", "-A"); git(self.ws, "commit", "-q", "-m", "head")
        self.head = git(self.ws, "rev-parse", "HEAD")
        (self.ws / ".onecompany").mkdir()
        (self.ws / ".onecompany" / "queue.json").write_text(json.dumps({"schema_version": "1.1", "work_units": []}))
        (self.ws / ".onecompany" / "portfolio.json").write_text(json.dumps({"entities": [{"id": "EPIC-9"}], "links": []}))
        self.brief = self.tmp / "brief.json"
        self.before = digests(self.ws, PRESERVED)

    def queue(self):
        return json.loads((self.ws / ".onecompany" / "queue.json").read_text())["work_units"]

    def approve(self, *extra):
        return cli("approve-brief", "--target", str(self.ws), "--repository", "demo/proj", "--brief", str(self.brief),
                   "--head", self.head, "--base", self.base, *extra)

    def test_journey_in_order(self):
        grant = ("--approve-wu", WU, "--owner-ack", "--planning-ref", "EPIC-9", "--write-scope", "src/**")

        # 1. No saved brief (or an incomplete one) can never be admitted.
        self.assertNotEqual(self.approve(*grant).returncode, 0)
        cli("brief", "--target", str(self.ws), "--repository", "demo/proj", "--audience", "Families",
            "--save-to", str(self.brief))
        self.assertNotEqual(self.approve(*grant).returncode, 0)
        self.assertEqual(self.queue(), [])
        self.brief.unlink(missing_ok=True)

        # 2. A complete saved brief is not approval.
        saved = cli("brief", "--target", str(self.ws), "--repository", "demo/proj", *ANSWERS,
                    "--save-to", str(self.brief))
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertNotIn("run_key", json.loads(self.brief.read_text()))
        self.assertEqual(self.queue(), [])

        # 3. Preview alone, or either flag alone, changes nothing.
        for extra in ((), ("--owner-ack",), ("--approve-wu", WU)):
            r = self.approve(*extra)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("PREVIEW_NOTHING_CHANGED", r.stdout)
            self.assertEqual(self.queue(), [])

        # 4. Explicit owner acknowledgement admits exactly one READY WU, with no lease or RunKey.
        r = self.approve(*grant)
        self.assertEqual(r.returncode, 0, r.stderr)
        units = self.queue()
        self.assertEqual(len(units), 1)
        unit = units[0]
        self.assertEqual((unit["id"], unit["status"]), (WU, "READY"))
        for forbidden in ("lease", "lease_id", "run_key", "branch_lease"):
            self.assertNotIn(forbidden, unit)
        self.assertEqual(unit["acceptance_criteria"], ["See a local checklist"])

        # 5. Real loopback runtime: ready_to_preview only with exact CI + test evidence.
        out = self.tmp / "runtime.json"
        bind = ["runtime-bind", "--wu", WU, "--run-key", RK, "--workspace", str(self.ws),
                "--head", self.head, "--base", self.base]
        for extra in ((), ("--ci", "success", "--tests", "failed"), ("--ci", "failure", "--tests", "passed")):
            blocked = cli(*bind, *extra)
            self.assertEqual(blocked.returncode, 1, extra)
            self.assertEqual(json.loads(blocked.stdout)["projection"]["state"], "blocked")
        ok = cli(*bind, "--ci", "success", "--tests", "passed", "--out", str(out))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bound = json.loads(ok.stdout)
        self.assertEqual(bound["projection"]["state"], "ready_to_preview")
        self.assertFalse(bound["projection"]["production_qualified"])
        manifest = bound["manifest"]
        self.assertEqual(manifest["health"]["status"], 200)
        self.assertTrue(manifest["crud_round_trip"]["ok"])
        self.assertTrue(manifest["cleanup"]["ok"])

        # 6. The manifest is invalid for a moved head or another RunKey.
        self.assertTrue(pa.rb.verify(manifest, wu_id=WU, run_key=RK, workspace=self.ws,
                                     head_sha=self.base, base_sha=self.base))
        self.assertIn("run_key mismatch", pa.rb.verify(manifest, wu_id=WU, run_key="run/other",
                                                       workspace=self.ws, head_sha=self.head, base_sha=self.base))

        # 7. Per-criterion evidence: covered only with a bound, digest-verified item.
        crit_doc = {"schema": pa.SCHEMA + "/criteria", "wu_id": WU,
                    "criteria": [{"id": "AC1", "required_kinds": ["api"]}]}
        approved = pa.criteria_digest(crit_doc["criteria"])
        ev_dir = self.tmp / "evidence"
        ev_dir.mkdir()
        (ev_dir / "api.txt").write_text("api proof")
        item = {"criterion_id": "AC1", "kind": "api", "result": "pass", "wu_id": WU, "run_key": RK,
                "head_sha": self.head, "base_sha": self.base, "build_digest": manifest["build_digest"],
                "artifact": "api.txt", "artifact_sha256": "sha256:" + hashlib.sha256(b"api proof").hexdigest()}

        def assure(items, criteria=crit_doc):
            (self.tmp / "criteria.json").write_text(json.dumps(criteria))
            (self.tmp / "evidence.json").write_text(json.dumps({"schema": pa.SCHEMA + "/evidence", "items": items}))
            return cli("postbind-assure", "--wu", WU, "--run-key", RK, "--workspace", str(self.ws),
                       "--head", self.head, "--base", self.base, "--criteria", str(self.tmp / "criteria.json"),
                       "--evidence", str(self.tmp / "evidence.json"), "--manifest", str(out),
                       "--evidence-dir", str(ev_dir), "--approved-criteria-sha256", approved)

        good = assure([item])
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertEqual(json.loads(good.stdout)["uncovered"], [])
        self.assertEqual(assure([]).returncode, 1)
        self.assertEqual(assure([dict(item, head_sha=self.base)]).returncode, 1)
        self.assertEqual(assure([dict(item, result="fail")]).returncode, 1)
        self.assertEqual(assure([dict(item, artifact_sha256="sha256:" + "0" * 64)]).returncode, 1)
        self.assertEqual(assure([item], criteria=dict(crit_doc, criteria=[])).returncode, 2)

        # 8. Existing project assets are preserved byte-for-byte.
        self.assertEqual(digests(self.ws, PRESERVED), self.before)


if __name__ == "__main__":
    unittest.main()
