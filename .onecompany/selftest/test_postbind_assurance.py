"""Post-binding assurance (OC-P0-15): per-criterion, exact-binding, fail-closed."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_PATH = ROOT / "examples" / "vertical-slice" / "app.py"
sys.path.insert(0, str(Path(__file__).parent))
from test_runtime_binding import make_workspace  # noqa: E402

_s = importlib.util.spec_from_file_location("postbind_assurance", ROOT / "scripts" / "postbind_assurance.py")
pa = importlib.util.module_from_spec(_s)
sys.modules[_s.name] = pa
_s.loader.exec_module(pa)
rb = pa.rb
WU, RK = "WU-T-1", "run/1"


@unittest.skipUnless(APP_PATH.is_file(), "source-only disposable demo not installed")
class PostbindAssuranceTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.ws, self.base, self.head = make_workspace(self._t.name)
        self.ev = Path(tempfile.mkdtemp(dir=self._t.name, prefix="ev-"))
        self.manifest = rb.capture(WU, RK, self.ws, self.head, self.base)
        self.criteria = {"schema": pa.SCHEMA + "/criteria", "wu_id": WU, "criteria": [
            {"id": "AC1", "required_kinds": ["api"]}, {"id": "AC2"}]}
        self.items = [self.item("AC1", "api", "a.txt"), self.item("AC2", "unit", "b.txt")]

    def item(self, cid, kind, name, content="proof"):
        (self.ev / name).write_text(content)
        d = "sha256:" + hashlib.sha256(content.encode()).hexdigest()
        return {"criterion_id": cid, "kind": kind, "result": "pass", "wu_id": WU, "run_key": RK,
                "head_sha": self.head, "base_sha": self.base, "build_digest": self.manifest["build_digest"],
                "artifact": name, "artifact_sha256": d}

    def run_assess(self, items=None, criteria=None, manifest=None, head=None):
        return pa.assess(criteria or self.criteria,
                         {"schema": pa.SCHEMA + "/evidence", "items": self.items if items is None else items},
                         manifest or self.manifest, wu_id=WU, run_key=RK, workspace=self.ws,
                         head_sha=head or self.head, base_sha=self.base, evidence_dir=self.ev)

    def test_all_covered_passes(self):
        r = self.run_assess()
        self.assertTrue(r["ok"], r); self.assertEqual(r["covered"], ["AC1", "AC2"]); self.assertEqual(r["uncovered"], [])

    def test_missing_criterion_named_and_never_pass(self):
        r = self.run_assess(items=self.items[:1])
        self.assertFalse(r["ok"]); self.assertEqual(r["uncovered"], ["AC2"])
        self.assertTrue(any("AC2" in p for p in r["problems"]))

    def test_required_kind_missing(self):
        r = self.run_assess(items=[self.item("AC1", "unit", "a.txt"), self.items[1]])
        self.assertFalse(r["ok"]); self.assertIn("AC1", r["uncovered"])

    def test_stale_binding_fields(self):
        for key, val in (("head_sha", "1" * 40), ("base_sha", "2" * 40), ("run_key", "other"),
                         ("wu_id", "WU-X"), ("build_digest", "sha256:" + "0" * 64)):
            with self.subTest(key=key):
                bad = copy.deepcopy(self.items); bad[1][key] = val
                r = self.run_assess(items=bad)
                self.assertFalse(r["ok"]); self.assertIn("AC2", r["uncovered"])
                self.assertTrue(any(key in p for p in r["problems"]))

    def test_fabricated_artifact_digest_or_missing_file(self):
        bad = copy.deepcopy(self.items); bad[1]["artifact_sha256"] = "sha256:" + "a" * 64
        self.assertIn("AC2", self.run_assess(items=bad)["uncovered"])
        bad = copy.deepcopy(self.items); bad[1]["artifact"] = "nope.txt"
        self.assertIn("AC2", self.run_assess(items=bad)["uncovered"])

    def test_unsafe_artifact_paths(self):
        outside = Path(self._t.name) / "outside.txt"; outside.write_text("proof")
        for path in ("../outside.txt", str(outside)):
            with self.subTest(path=path):
                bad = copy.deepcopy(self.items); bad[1]["artifact"] = path
                self.assertIn("AC2", self.run_assess(items=bad)["uncovered"])

    def test_symlink_artifact_refused(self):
        outside = Path(self._t.name) / "t.txt"; outside.write_text("proof")
        (self.ev / "link.txt").symlink_to(outside)
        bad = copy.deepcopy(self.items); bad[1]["artifact"] = "link.txt"
        self.assertIn("AC2", self.run_assess(items=bad)["uncovered"])

    def test_non_pass_and_unknown_inputs(self):
        bad = copy.deepcopy(self.items); bad[1]["result"] = "fail"
        self.assertIn("AC2", self.run_assess(items=bad)["uncovered"])
        bad = copy.deepcopy(self.items); bad[1]["kind"] = "vibes"
        self.assertIn("AC2", self.run_assess(items=bad)["uncovered"])
        extra = self.items + [self.item("AC9", "unit", "c.txt")]
        r = self.run_assess(items=extra)
        self.assertFalse(r["ok"]); self.assertTrue(any("unknown criterion" in p for p in r["problems"]))

    def test_head_moved_fails_via_runtime_binding(self):
        r = self.run_assess(head="3" * 40)
        self.assertFalse(r["ok"]); self.assertTrue(any(p.startswith("runtime binding:") for p in r["problems"]))

    def test_failed_runtime_manifest_blocks_everything(self):
        m = copy.deepcopy(self.manifest); m["health"] = {"status": 500}
        r = self.run_assess(manifest=m)
        self.assertFalse(r["ok"]); self.assertTrue(any("health" in p for p in r["problems"]))

    def test_malformed_documents(self):
        with self.assertRaises(pa.AssuranceError):
            self.run_assess(criteria={"schema": "x"})
        dup = copy.deepcopy(self.criteria); dup["criteria"].append({"id": "AC1"})
        with self.assertRaises(pa.AssuranceError):
            self.run_assess(criteria=dup)
        r = pa.assess(self.criteria, None, self.manifest, wu_id=WU, run_key=RK, workspace=self.ws,
                      head_sha=self.head, base_sha=self.base, evidence_dir=self.ev)
        self.assertFalse(r["ok"]); self.assertEqual(r["covered"], [])

    def test_cli_exit_codes(self):
        d = Path(self._t.name)
        (d / "c.json").write_text(json.dumps(self.criteria))
        (d / "e.json").write_text(json.dumps({"schema": pa.SCHEMA + "/evidence", "items": self.items}))
        (d / "m.json").write_text(json.dumps({"manifest": self.manifest}))
        args = ["--wu", WU, "--run-key", RK, "--workspace", self.ws, "--head", self.head, "--base", self.base,
                "--criteria", str(d / "c.json"), "--evidence", str(d / "e.json"), "--manifest", str(d / "m.json"),
                "--evidence-dir", str(self.ev)]
        self.assertEqual(pa.main(args), 0)
        (d / "e.json").write_text(json.dumps({"schema": pa.SCHEMA + "/evidence", "items": self.items[:1]}))
        self.assertEqual(pa.main(args), 1)
        (d / "c.json").write_text("{not json")
        self.assertEqual(pa.main(args), 2)


if __name__ == "__main__":
    unittest.main()
