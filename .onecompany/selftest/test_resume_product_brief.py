"""Fail-closed saved Product Brief resume tests using actual producer contract."""
from __future__ import annotations

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

SPEC = importlib.util.spec_from_file_location("resume_product_brief", SCRIPTS / "resume_product_brief.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def draft() -> dict:
    """Use the real producer so all required owner and authority fields exist."""
    assessment = {
        "journey": {
            "path": "create",
            "safety_blockers": [],
            "product_brief_draft": {
                "project_name": "Example",
                "repository": "NTinkicht/example",
                "branch": "main",
                "known_stack": [],
                "existing_tests": [],
                "existing_ci": [],
                "known_contracts": [],
            },
        },
    }
    return make_draft(assessment, {
        "audience": "Patients", "problem": "Waiting", "outcome": "Clarity",
        "first_feature": "Status", "constraints": None,
    })


class ResumeProductBriefTests(unittest.TestCase):
    """Resume never infers owner authorization or follows untrusted paths."""

    def write(self, folder: Path, payload: dict) -> Path:
        """Write one disposable owner draft to inspect."""
        path = folder / "brief.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_complete_draft_is_read_only_and_not_authorized(self):
        """An actual producer-shaped draft remains explicitly unauthorized."""
        with tempfile.TemporaryDirectory() as td:
            result = MOD.summarize(MOD.load_draft(self.write(Path(td), draft())))
            self.assertEqual(result["missing_required"], [])
            self.assertFalse(result["implementation_authorized"])
            self.assertIn("grants no approval", result["next_action"])

    def test_missing_answer_remains_blocked(self):
        """An honest incomplete draft is displayable but cannot advance."""
        with tempfile.TemporaryDirectory() as td:
            payload = draft()
            payload["answers"]["outcome"] = None
            payload["missing_required_answers"] = ["outcome"]
            payload["next_action"] = (
                "Provide the missing required owner answers; do not begin implementation."
            )
            result = MOD.summarize(MOD.load_draft(self.write(Path(td), payload)))
            self.assertEqual(result["missing_required"], ["outcome"])
            self.assertIn("do not begin implementation", result["next_action"])

    def test_authority_and_contradictory_drafts_are_refused(self):
        """Reject approval, lease, claims, stale answers and unsafe discovery."""
        cases = [
            ("approval", lambda b: b["approval"].update(implementation=True)),
            ("numeric false-like approval", lambda b: b["approval"].update(implementation=0)),
            ("lease", lambda b: b.update(write_lease_granted=True)),
            ("qualified", lambda b: b.update(qualified_implementer_selected=True)),
            ("qualified missing", lambda b: b.pop("qualified_implementer_selected")),
            ("nonempty criteria", lambda b: b.update(acceptance_criteria=["Injected"])),
            ("safety blocker", lambda b: b.update(safety_blockers=["unsafe"])),
            ("missing-answer mismatch", lambda b: b.update(missing_required_answers=["outcome"])),
            ("unknown authority", lambda b: b.update(run_key="forged")),
            ("non-text", lambda b: b["answers"].update(outcome=17)),
            ("unbounded", lambda b: b["answers"].update(outcome="X" * 1001)),
            ("blank unnormalized", lambda b: b["answers"].update(outcome="")),
            ("missing answers key", lambda b: b["answers"].pop("outcome")),
            ("unknown answers key", lambda b: b["answers"].update(approved=True)),
            ("next step conflict", lambda b: b.update(next_action="Go live")),
            ("wrong source", lambda b: b.update(source="forged")),
            ("invalid project", lambda b: b["project"].update(path="source")),
            ("terminal-control project", lambda b: b["project"].update(name="Fake\x1b[2Japproved")),
        ]
        with tempfile.TemporaryDirectory() as td:
            for name, mutation in cases:
                with self.subTest(name=name):
                    payload = draft()
                    mutation(payload)
                    with self.assertRaises((ValueError, TypeError)):
                        MOD.load_draft(self.write(Path(td), payload))

    @unittest.skipUnless(os.name == "posix", "nofollow descriptor tests require POSIX")
    def test_symlink_and_symlink_parent_are_refused(self):
        """Secure openat prevents final and intermediate path traversal."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            target = self.write(folder, draft())
            link = folder / "link.json"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                MOD.load_draft(link)
            parent = folder / "linked-parent"
            parent.symlink_to(folder, target_is_directory=True)
            with self.assertRaises(OSError):
                MOD.load_draft(parent / "brief.json")

    @unittest.skipUnless(os.name == "posix", "swap test requires POSIX")
    def test_swap_during_open_refuses_without_reading_target(self):
        """Replacement symlink appearing at open cannot bypass O_NOFOLLOW."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            source = self.write(folder, draft())
            alternate = folder / "alternate.json"
            alternate.write_text('{"sensitive":true}', encoding="utf-8")
            real_open = os.open
            swapped = False

            def swap(path, flags, *args, **kwargs):
                nonlocal swapped
                if path == "brief.json" and not swapped:
                    swapped = True
                    source.unlink()
                    source.symlink_to(alternate)
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(MOD.os, "open", side_effect=swap):
                with self.assertRaises(OSError):
                    MOD.load_draft(source)
            self.assertTrue(swapped)

    @unittest.skipUnless(os.name == "posix", "flags simulation requires POSIX")
    def test_missing_nofollow_fails_closed(self):
        """No insecure platform fallback silently follows a symlink."""
        with tempfile.TemporaryDirectory() as td:
            path = self.write(Path(td), draft())
            with mock.patch.object(MOD.os, "O_NOFOLLOW", 0):
                with self.assertRaisesRegex(ValueError, "secure resume"):
                    MOD.load_draft(path)
            with mock.patch.object(MOD.os, "O_NONBLOCK", 0):
                with self.assertRaisesRegex(ValueError, "secure resume"):
                    MOD.load_draft(path)

    @unittest.skipUnless(os.name == "posix", "FIFO tests require POSIX")
    def test_fifo_and_dynamic_oversize_refused(self):
        """Nonblocking open rejects FIFOs and read cap handles stale metadata."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            fifo = folder / "fifo.json"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "regular file"):
                MOD.load_draft(fifo)
            big = folder / "big.json"
            big.write_bytes(b"{" + b" " * MOD.MAX_BYTES + b"}")
            with self.assertRaisesRegex(ValueError, "no larger"):
                MOD.load_draft(big)
            original = os.fstat

            def stale_metadata(fd):
                metadata = original(fd)
                return type("OldSize", (), {
                    "st_mode": metadata.st_mode, "st_size": 2,
                })()

            with mock.patch.object(MOD.os, "fstat", side_effect=stale_metadata):
                with self.assertRaisesRegex(ValueError, "no larger"):
                    MOD.load_draft(big)

    def test_malformed_json_is_cli_refusal(self):
        """Bad owner input returns a bounded error rather than success."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            for raw in ("[]", "{broken"):
                with self.subTest(raw=raw):
                    path.write_text(raw, encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, str(SCRIPTS / "resume_product_brief.py"),
                         str(path)],
                        cwd=ROOT, text=True, capture_output=True, timeout=12,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("REFUSED:", result.stderr)


if __name__ == "__main__":
    unittest.main()
