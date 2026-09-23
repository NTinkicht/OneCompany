"""Real producer-shaped, fail-closed read-only Product Brief comparison tests."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from product_brief import make_draft

SPEC = importlib.util.spec_from_file_location("product_brief_diff", SCRIPTS / "product_brief_diff.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def brief() -> dict:
    """Generate an exact contract using the real Product Brief producer."""
    assessment = {
        "journey": {
            "path": "adopt",
            "safety_blockers": [],
            "product_brief_draft": {
                "project_name": "Example",
                "repository": "NTinkicht/example",
                "branch": "main",
                "known_stack": ["Python"],
                "existing_tests": ["tests"],
                "existing_ci": ["GitHub Actions"],
                "known_contracts": ["PRODUCT.md"],
            },
        },
    }
    return make_draft(assessment, {
        "audience": "Parents",
        "problem": "Delayed information",
        "outcome": "Understand appointments",
        "first_feature": "View today's appointments",
        "constraints": None,
    })


class ProductBriefDiffTests(unittest.TestCase):
    """Only an unchanged producer contract may cross the comparison boundary."""

    def write(self, folder: Path, name: str, payload: dict) -> Path:
        """Create a disposable JSON draft with explicit owner test answers."""
        path = folder / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_full_real_drafts_only_changed_answer_fields_and_no_authority(self):
        """Exercise the actual producer, bounded reader, comparison and CLI."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            before = brief()
            after = copy.deepcopy(before)
            after["answers"]["outcome"] = "See upcoming appointments"
            first = self.write(folder, "before.json", before)
            second = self.write(folder, "after.json", after)
            result = MOD.compare(MOD.load(first), MOD.load(second))
            self.assertEqual([c["field"] for c in result["changed_fields"]], ["outcome"])
            self.assertEqual(result["status"], "PREVIEW_ONLY_NOT_APPROVED")
            self.assertIs(result["implementation_authorized"], False)
            run = subprocess.run(
                [sys.executable, str(SCRIPTS / "product_brief_diff.py"),
                 str(first), str(second), "--json"],
                cwd=ROOT, text=True, capture_output=True, timeout=12,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout), result)
            self.assertEqual(json.loads(first.read_text()), before)

    def test_identical_drafts_have_no_changes(self):
        """No synthetic changed fields may appear for identical owner intent."""
        self.assertEqual(MOD.compare(brief(), brief())["changed_fields"], [])

    def test_authority_and_malformed_drafts_refuse(self):
        """Reject every known approval, lease, forged field and schema mismatch."""
        scenarios = [
            ("selected implementer", lambda b: b.update(qualified_implementer_selected=True)),
            ("missing implementer", lambda b: b.pop("qualified_implementer_selected")),
            ("lease", lambda b: b.update(write_lease_granted=True)),
            ("approve", lambda b: b["approval"].update(implementation=True)),
            ("criteria", lambda b: b.update(acceptance_criteria=["untrusted"])),
            ("extra authority", lambda b: b.update(run_key="forged")),
            ("missing answer field", lambda b: b["answers"].pop("outcome")),
            ("extra answer field", lambda b: b["answers"].update(owner_approved=True)),
            ("nontext answer", lambda b: b["answers"].update(outcome=17)),
            ("unbounded answer", lambda b: b["answers"].update(outcome="A" * 1001)),
            ("noncanonical spacing", lambda b: b["answers"].update(outcome="  unexpected  ")),
            ("inconsistent missing", lambda b: b.update(missing_required_answers=["outcome"])),
            ("wrong source", lambda b: b.update(source="trusted_approval")),
            ("wrong kind", lambda b: b.update(document_kind="execution_approval")),
            ("wrong status", lambda b: b.update(status="APPROVED")),
            ("wrong project", lambda b: b["project"].update(path="source")),
            ("unknown project field", lambda b: b["project"].update(write_lease=True)),
            ("wrong next step", lambda b: b.update(next_action="Start production")),
        ]
        with tempfile.TemporaryDirectory() as td:
            for name, mutate in scenarios:
                with self.subTest(name=name):
                    candidate = brief()
                    mutate(candidate)
                    with self.assertRaises((ValueError, TypeError)):
                        MOD.load(self.write(Path(td), "bad.json", candidate))

    def test_incomplete_but_honest_draft_remains_comparable(self):
        """Missing owner answers remain missing, not invented or promoted."""
        candidate = brief()
        candidate["answers"]["outcome"] = None
        candidate["missing_required_answers"] = ["outcome"]
        candidate["next_action"] = (
            "Provide the missing required owner answers; do not begin implementation."
        )
        result = MOD.compare(brief(), candidate)
        self.assertEqual(result["changed_fields"][0]["after"], None)
        self.assertIs(result["implementation_authorized"], False)

    def test_cross_project_diff_refused(self):
        """Never silently compare and misattribute separate project intents."""
        candidate = brief()
        candidate["project"]["repository"] = "NTinkicht/other"
        with self.assertRaisesRegex(ValueError, "project/discovery mismatch"):
            MOD.compare(brief(), candidate)

    @unittest.skipUnless(os.name == "posix", "secure openat tests require POSIX")
    def test_final_and_parent_symlinks_refuse(self):
        """Neither the file nor any intermediate directory can redirect input."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            source = self.write(folder, "draft.json", brief())
            link = folder / "link.json"
            link.symlink_to(source)
            with self.assertRaises(OSError):
                MOD.load(link)
            parent = folder / "linked-parent"
            parent.symlink_to(folder, target_is_directory=True)
            with self.assertRaises(OSError):
                MOD.load(parent / "draft.json")

    @unittest.skipUnless(os.name == "posix", "descriptor-swap test requires POSIX")
    def test_replaced_final_path_cannot_follow_symlink(self):
        """An attacker swapping the pathname just before open cannot redirect FD."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            source = self.write(folder, "draft.json", brief())
            destination = self.write(folder, "outside.json", brief())
            actual_open = os.open
            swapped = False

            def race_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if str(path) == "draft.json" and not swapped:
                    swapped = True
                    source.unlink()
                    source.symlink_to(destination)
                return actual_open(path, flags, *args, **kwargs)

            with mock.patch.object(MOD.os, "open", side_effect=race_open):
                with self.assertRaises(OSError):
                    MOD.load(source)
            self.assertTrue(swapped)

    @unittest.skipUnless(os.name == "posix", "FIFO test requires POSIX")
    def test_fifo_and_oversize_refuse_without_hang(self):
        """O_NONBLOCK+fstat avoids FIFO hangs; a later-grown file stays bounded."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            fifo = folder / "pipe.json"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "regular bounded"):
                MOD.load(fifo)
            big = folder / "big.json"
            big.write_bytes(b"{" + b" " * MOD.MAX_BYTES + b"}")
            with self.assertRaisesRegex(ValueError, "regular bounded"):
                MOD.load(big)
            real_fstat = os.fstat

            def old_metadata(fd):
                meta = real_fstat(fd)
                return type("StaleSize", (), {"st_mode": meta.st_mode, "st_size": 2})()

            with mock.patch.object(MOD.os, "fstat", side_effect=old_metadata):
                with self.assertRaisesRegex(ValueError, "exceeds"):
                    MOD.load(big)

    @unittest.skipUnless(os.name == "posix", "safe flags require POSIX")
    def test_missing_nonblock_or_nofollow_fails_closed(self):
        """No platform fallback may block on FIFO or follow attacker links."""
        with tempfile.TemporaryDirectory() as td:
            path = self.write(Path(td), "brief.json", brief())
            for flag in ("O_NOFOLLOW", "O_NONBLOCK"):
                with self.subTest(flag=flag):
                    with mock.patch.object(MOD.os, flag, 0):
                        with self.assertRaisesRegex(ValueError, "secure Product Brief"):
                            MOD.load(path)

    def test_bad_json_or_list_refuses_in_cli(self):
        """Malformed inputs do not crash or produce misleading comparison."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            candidate = folder / "bad.json"
            for raw in ('[1]', '{broken'):
                with self.subTest(raw=raw):
                    candidate.write_text(raw)
                    run = subprocess.run(
                        [sys.executable, str(SCRIPTS / "product_brief_diff.py"),
                         str(candidate), str(candidate)],
                        cwd=ROOT, text=True, capture_output=True, timeout=12,
                    )
                    self.assertEqual(run.returncode, 2)
                    self.assertIn("REFUSED:", run.stderr)


if __name__ == "__main__":
    unittest.main()
