"""Tests for owner-acknowledged single-WU admission from a saved brief."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import brief_approval as ba
import product_brief

HEAD, BASE = "a" * 40, "b" * 40
APPROVAL = ("--planning-ref", "EPIC-9", "--write-scope", "src/**", "--write-scope", "tests/**")
ANSWERS = {"audience": "Families", "problem": "Keep track of small tasks",
           "outcome": "See a local checklist", "first_feature": "Add and finish a checklist item",
           "constraints": "No personal data"}


class BriefApprovalTests(unittest.TestCase):
    """Prove admission is bound, idempotent, minimal and fail-closed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / "proj"
        (self.target / ".onecompany").mkdir(parents=True)
        self.queue = self.target / ".onecompany" / "queue.json"
        self.write_queue([])
        self.portfolio = self.target / ".onecompany" / "portfolio.json"
        self.portfolio.write_text(json.dumps({"entities": [{"id": "EPIC-9"}], "links": []}))
        self.brief = Path(self.tmp.name) / "brief.json"
        self.save(self.make())

    def make(self, answers=None):
        assessment = product_brief.analyze(self.target, repository="demo/proj")
        return product_brief.make_draft(assessment, answers or ANSWERS)

    def save(self, data):
        self.brief.write_text(json.dumps(data))

    def write_queue(self, units):
        self.queue.write_text(json.dumps({"schema_version": "1.1", "work_units": units}))

    def units(self):
        return json.loads(self.queue.read_text())["work_units"]

    def run_cli(self, *extra, head=HEAD, base=BASE):
        argv = ["--target", str(self.target), "--repository", "demo/proj",
                "--brief", str(self.brief), "--head", head, "--base", base, *extra]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ba.main(argv)
        return code, out.getvalue(), err.getvalue()

    def admit(self, wu="WU-APP-001"):
        return self.run_cli("--approve-wu", wu, "--owner-ack", *APPROVAL)

    def test_preview_without_both_flags_changes_nothing(self):
        before = self.queue.read_text()
        for extra in ((), ("--owner-ack",), ("--approve-wu", "WU-APP-001")):
            code, out, _ = self.run_cli(*extra)
            self.assertEqual(code, 2)
            self.assertIn("PREVIEW_NOTHING_CHANGED", out)
            self.assertEqual(self.queue.read_text(), before)

    def test_admits_exactly_one_ready_unit_with_owner_criteria_and_no_authority(self):
        code, out, err = self.admit()
        self.assertEqual((code, err), (0, ""))
        units = self.units()
        self.assertEqual(len(units), 1)
        unit = units[0]
        self.assertEqual(unit["status"], "READY")
        self.assertEqual(unit["acceptance_criteria"], [ANSWERS["outcome"]])
        for forbidden in ("lease", "lease_id", "run_key", "branch_lease"):
            self.assertNotIn(forbidden, unit)
        self.assertIsNone(unit["branch"])
        self.assertEqual(unit["planning_refs"], ["EPIC-9"])
        self.assertEqual(unit["write_scope"], ["src/**", "tests/**"])
        links = json.loads(self.portfolio.read_text())["links"]
        self.assertEqual([(l["source"], l["target"], l["relationship"]) for l in links],
                         [("EPIC-9", "WU-APP-001", "delivers")])
        self.assertEqual(unit["brief_approval"]["head"], HEAD)
        self.assertEqual(unit["brief_approval"]["brief_sha256"], ba.digest(json.loads(self.brief.read_text())))

    def test_second_identical_run_is_idempotent(self):
        self.admit()
        snapshot = self.queue.read_text()
        code, out, _ = self.admit()
        self.assertEqual(code, 0)
        self.assertIn("ALREADY_ADMITTED", out)
        self.assertEqual(self.queue.read_text(), snapshot)

    def test_changed_head_base_or_brief_invalidates_existing_approval(self):
        self.admit()
        code, _, err = self.run_cli("--approve-wu", "WU-APP-001", "--owner-ack", *APPROVAL, head="c" * 40)
        self.assertEqual(code, 2)
        self.assertIn("WU_ID_EXISTS_WITH_DIFFERENT_APPROVAL", err)
        code, _, err = self.run_cli("--approve-wu", "WU-APP-001", "--owner-ack", *APPROVAL, base="c" * 40)
        self.assertIn("WU_ID_EXISTS_WITH_DIFFERENT_APPROVAL", err)
        self.save(self.make(dict(ANSWERS, outcome="Something else")))
        code, _, err = self.admit()
        self.assertIn("WU_ID_EXISTS_WITH_DIFFERENT_APPROVAL", err)
        self.assertEqual(len(self.units()), 1)

    def refused(self, reason, *extra, **kw):
        before = self.queue.read_text()
        code, _, err = self.run_cli(*(extra or ("--approve-wu", "WU-APP-001", "--owner-ack", *APPROVAL)), **kw)
        self.assertEqual(code, 2)
        self.assertIn(reason, err)
        self.assertEqual(self.queue.read_text(), before)

    def test_refuses_incomplete_brief(self):
        self.save(self.make(dict(ANSWERS, outcome="")))
        self.refused("COMPLETE_VALIDATED_BRIEF_REQUIRED")

    def test_refuses_forged_authority_fields_and_injected_criteria(self):
        good = json.loads(self.brief.read_text())
        for key, value in (("run_key", "RK-1"), ("lease_id", "L-1"), ("acceptance_criteria", ["rm -rf"]),
                           ("approval", {"product_brief": True, "implementation": True, "deployment": True}),
                           ("write_lease_granted", True)):
            with self.subTest(key=key):
                forged = copy.deepcopy(good)
                forged[key] = value
                self.save(forged)
                self.refused("SAVED_BRIEF_STALE_OR_AUTHORITY_BEARING")

    def test_refuses_oversized_symlink_and_non_regular_brief(self):
        self.brief.write_text(json.dumps(dict(self.make(), pad="x" * 17000)))
        self.refused("SAVED_BRIEF_TOO_LARGE")
        real = Path(self.tmp.name) / "real.json"
        real.write_text(json.dumps(self.make()))
        self.brief.unlink()
        os.symlink(real, self.brief)
        before = self.queue.read_text()
        code, _, err = self.admit()
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("REFUSED"))
        self.assertEqual(self.queue.read_text(), before)
        self.brief.unlink()
        os.mkfifo(self.brief)
        code, _, err = self.admit()
        self.assertEqual(code, 2)
        self.assertIn("SAVED_BRIEF_FILE_REQUIRED", err)

    def test_refuses_stale_repository_path_or_branch(self):
        stale = self.make()
        stale["project"]["repository"] = "other/repo"
        self.save(stale)
        self.refused("SAVED_BRIEF_STALE_OR_AUTHORITY_BEARING")

    def test_refuses_moved_or_malformed_revisions(self):
        self.refused("EXACT_DISTINCT_REVISIONS_REQUIRED", head=HEAD, base=HEAD)
        self.refused("EXACT_DISTINCT_REVISIONS_REQUIRED", head="abc", base=BASE)

    def test_refuses_bad_wu_id(self):
        for bad in ("APP-1", "WU bad", "WU/../x", ""):
            with self.subTest(bad=bad):
                self.refused("UNKNOWN_WU_ID", "--approve-wu", bad, "--owner-ack", *APPROVAL)

    def test_refuses_when_project_has_active_stream(self):
        self.write_queue([{"id": "WU-OTHER-1", "status": "IN_PROGRESS"}])
        self.refused("ACTIVE_WU_STREAM_PRESENT")
        self.write_queue([{"id": "WU-OTHER-1", "status": "DONE"}])
        self.assertEqual(self.admit()[0], 0)
        self.assertEqual(len(self.units()), 2)

    def test_refuses_missing_or_symlinked_queue(self):
        real = Path(self.tmp.name) / "q.json"
        real.write_text(self.queue.read_text())
        self.queue.unlink()
        code, _, err = self.admit()
        self.assertEqual(code, 2)
        self.assertIn("TARGET_QUEUE_NOT_FOUND", err)
        self.assertFalse(self.queue.exists())
        os.symlink(real, self.queue)
        code, _, err = self.admit()
        self.assertEqual(code, 2)
        self.assertIn("TARGET_QUEUE_UNSAFE", err)

    def test_refuses_missing_unknown_planning_ref_and_bad_write_scope(self):
        self.refused("PLANNING_REF_REQUIRED", "--approve-wu", "WU-APP-001", "--owner-ack",
                     "--write-scope", "src/**")
        self.refused("UNKNOWN_PLANNING_REF", "--approve-wu", "WU-APP-001", "--owner-ack",
                     "--planning-ref", "NOPE", "--write-scope", "src/**")
        self.refused("WRITE_SCOPE_REQUIRED", "--approve-wu", "WU-APP-001", "--owner-ack",
                     "--planning-ref", "EPIC-9")
        for bad in ("**/*", "/etc", "../x", "a/../b", "*"):
            with self.subTest(bad=bad):
                self.refused("WRITE_SCOPE_INVALID", "--approve-wu", "WU-APP-001", "--owner-ack",
                             "--planning-ref", "EPIC-9", "--write-scope", bad)

    def test_refuses_symlinked_control_directory(self):
        outside = Path(self.tmp.name) / "outside"
        (self.target / ".onecompany").rename(outside)
        os.symlink(outside, self.target / ".onecompany")
        before = (outside / "queue.json").read_text()
        code, _, err = self.admit()
        self.assertEqual(code, 2)
        self.assertIn("TARGET_QUEUE_UNSAFE", err)
        self.assertEqual((outside / "queue.json").read_text(), before)

    def test_apply_is_serialized_by_exclusive_lock(self):
        import fcntl
        import threading
        import time
        lock = os.open(self.target / ".onecompany" / ".brief-approval.lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        done = []
        worker = threading.Thread(target=lambda: done.append(self.admit()))
        worker.start()
        time.sleep(0.5)
        self.assertEqual(done, [])
        self.assertEqual(self.units(), [])
        fcntl.flock(lock, fcntl.LOCK_UN)
        os.close(lock)
        worker.join(10)
        self.assertEqual(done[0][0], 0)
        self.assertEqual(len(self.units()), 1)

    def test_module_has_no_network_or_provider_imports(self):
        source = (ROOT / "scripts" / "brief_approval.py").read_text()
        for name in ("urllib", "socket", "http", "requests", "subprocess"):
            self.assertNotIn("import " + name, source)


if __name__ == "__main__":
    unittest.main()
