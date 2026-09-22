"""Tests for real guided first-run Create/Adopt continuation, not execution."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import first_run_journey as journey
import product_brief


class FirstRunJourneyTests(unittest.TestCase):
    """Exercise both real discovery paths and refusal of forged authority."""

    @staticmethod
    def answers() -> dict[str, str]:
        return {
            "audience": "Families",
            "problem": "Keep track of small tasks",
            "outcome": "See a local checklist",
            "first_feature": "Add and finish a checklist item",
            "constraints": "No personal data",
        }

    def test_new_project_guides_owner_without_creating_target(self):
        """A fresh Create path must be non-mutating and propose only a brief."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fresh"
            assessment = product_brief.analyze(target, repository="demo/fresh")
            result = journey.view(assessment)
            self.assertEqual(result["path"], "create")
            self.assertEqual(result["stage"], "NEEDS_PRODUCT_BRIEF")
            self.assertEqual(result["approval"], "NOT_GRANTED")
            self.assertEqual(result["missing_required_answers"],
                             ["audience", "problem", "outcome", "first_feature"])
            self.assertEqual(result["next_commands_argv"][0][:3],
                             ["python", "onecompany.py", "brief"])
            self.assertFalse(target.exists())
            self.assertIsNone(result["run_key"])

    def test_adopt_preserves_discovered_tests_ci_and_contracts(self):
        """Adopt displays actual target assets instead of inventing product state."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "pyproject.toml").write_text("[project]\\nname='x'\\n")
            (target / "tests").mkdir()
            (target / ".github" / "workflows").mkdir(parents=True)
            (target / ".github" / "workflows" / "ci.yml").write_text("name: CI\\n")
            (target / "SECURITY.md").write_text("Example contract\\n")
            assessment = product_brief.analyze(target, repository="demo/existing")
            result = journey.view(assessment)
            self.assertEqual(result["path"], "adopt")
            self.assertIn("Python", result["project"]["stack"])
            self.assertIn("tests", result["project"]["tests"])
            self.assertIn("GitHub Actions (1 workflow)", result["project"]["ci"])
            self.assertIn("SECURITY.md", result["project"]["contracts"])
            self.assertFalse((target / ".onecompany").exists())

    def test_owner_filled_brief_still_only_read_only_proposal(self):
        """A complete owner draft cannot silently approve execution."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "future"
            assessment = product_brief.analyze(target, repository="demo/future")
            brief = product_brief.make_draft(assessment, self.answers())
            result = journey.view(assessment, brief, "/tmp/brief.json")
            self.assertEqual(result["stage"], "PROPOSAL_READY_NOT_APPROVED")
            self.assertEqual(result["missing_required_answers"], [])
            self.assertEqual(result["approval"], "NOT_GRANTED")
            self.assertIsNone(result["lease_id"])
            self.assertIsNone(result["canonical_work_unit"])
            self.assertFalse(result["model_qualified"])
            self.assertFalse(result["deployment_ready"])
            self.assertEqual(result["requested_extra_spend"], 0)
            cmd = result["next_commands_argv"][0]
            self.assertEqual(cmd[1:3], ["onecompany.py", "journey"])
            self.assertIn("--emit-proposal", cmd)
            self.assertIn(str(target), cmd)
            self.assertIn("demo/future", cmd)
            self.assertIn("<LIVE_HEAD_SHA>", cmd)
            self.assertFalse(target.exists())

    def test_stale_discovery_approval_and_authority_smuggling_refused(self):
        """Saved drafts that disagree with canonical discovery fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "adopt"
            target.mkdir()
            assessment = product_brief.analyze(target, repository="demo/adopt")
            original = product_brief.make_draft(assessment, self.answers())
            variants = []
            for field, value in [
                ("status", "APPROVED"), ("run_key", "forged"),
                ("write_lease_granted", True), ("acceptance_criteria", ["ship"]),
            ]:
                candidate = dict(original)
                candidate[field] = value
                variants.append(candidate)
            altered = dict(original)
            altered["project"] = dict(original["project"])
            altered["project"]["repository"] = "attacker/other"
            variants.append(altered)
            altered = dict(original)
            altered["approval"] = dict(original["approval"])
            altered["approval"]["implementation"] = True
            variants.append(altered)
            for candidate in variants:
                with self.subTest(candidate=candidate):
                    with self.assertRaisesRegex(ValueError, "STALE_OR_AUTHORITY"):
                        journey.view(assessment, candidate)
            (target / "tests").mkdir()  # Newly discovered asset invalidates old brief.
            fresh = product_brief.analyze(target, repository="demo/adopt")
            with self.assertRaisesRegex(ValueError, "STALE_OR_AUTHORITY"):
                journey.view(fresh, original)

    def test_bounded_saved_brief_rejects_symlinks_and_oversize(self):
        """Untrusted external briefs are bounded and never followed via symlink."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            payload = folder / "brief.json"
            payload.write_text("x" * 16385)
            with self.assertRaisesRegex(ValueError, "TOO_LARGE"):
                journey.read_brief(payload)
            payload.write_text("[]")
            with self.assertRaisesRegex(ValueError, "OBJECT_REQUIRED"):
                journey.read_brief(payload)
            shortcut = folder / "link.json"
            shortcut.symlink_to(payload)
            with self.assertRaisesRegex(ValueError, "FILE_REQUIRED"):
                journey.read_brief(shortcut)

    def test_symlink_swap_during_open_is_refused_atomically(self):
        """A last-moment symlink replacement cannot defeat O_NOFOLLOW."""
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("atomic O_NOFOLLOW unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            payload = folder / "draft.json"
            victim = folder / "victim.json"
            payload.write_text('{"document_kind":"product_brief_draft"}')
            victim.write_text('{"secret":"must not be read"}')
            original_open = os.open

            def replace_just_before_open(path, flags, *args, **kwargs):
                if Path(path) == payload:
                    payload.unlink()
                    payload.symlink_to(victim)
                return original_open(path, flags, *args, **kwargs)

            with patch.object(journey.os, "open", side_effect=replace_just_before_open):
                with self.assertRaises(OSError):
                    journey.read_brief(payload)
            self.assertEqual(victim.read_text(), '{"secret":"must not be read"}')

    def test_emitted_handoff_revalidates_same_saved_brief_and_refs(self):
        """Continuation does not fall back to the weaker standalone reader."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "future"
            report = product_brief.analyze(target, repository="demo/future")
            draft = product_brief.make_draft(report, self.answers())
            saved = Path(tmp) / "draft.json"
            saved.write_text(json.dumps(draft))
            head, base = "a" * 40, "b" * 40
            with contextlib.redirect_stdout(io.StringIO()) as output:
                rc = journey.main([
                    "--target", str(target), "--repository", "demo/future",
                    "--brief", str(saved), "--emit-proposal",
                    "--head", head, "--base", base,
                ])
            self.assertEqual(rc, 0)
            proposal = json.loads(output.getvalue())
            self.assertEqual(proposal["source_refs_unverified"],
                             {"head": head, "base": base})
            self.assertEqual(proposal["authorization"], "NOT_GRANTED")
            self.assertIsNone(proposal["run_key"])
            tampered = dict(draft)
            tampered["run_key"] = "forged"
            saved.write_text(json.dumps(tampered))
            with contextlib.redirect_stderr(io.StringIO()):
                rc = journey.main([
                    "--target", str(target), "--repository", "demo/future",
                    "--brief", str(saved), "--emit-proposal",
                    "--head", head, "--base", base,
                ])
            self.assertEqual(rc, 2)
            saved.write_text(json.dumps(draft))
            target.mkdir()
            (target / "tests").mkdir()
            with contextlib.redirect_stderr(io.StringIO()):
                rc = journey.main([
                    "--target", str(target), "--repository", "demo/future",
                    "--brief", str(saved), "--emit-proposal",
                    "--head", head, "--base", base,
                ])
            self.assertEqual(rc, 2)

    def test_cli_end_to_end_create_and_no_mutation(self):
        """The actual route prints a structured proposal, with no target writes."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "new"
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = journey.main([
                    "--target", str(target), "--repository", "demo/new",
                    "--json",
                ])
            self.assertEqual(code, 2)  # Owner answers still required.
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["stage"], "NEEDS_PRODUCT_BRIEF")
            self.assertFalse(target.exists())
            assessment = product_brief.analyze(target, repository="demo/new")
            draft = product_brief.make_draft(assessment, self.answers())
            saved = Path(tmp) / "saved.json"
            saved.write_text(json.dumps(draft))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = journey.main([
                    "--target", str(target), "--repository", "demo/new",
                    "--brief", str(saved), "--json",
                ])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["stage"], "PROPOSAL_READY_NOT_APPROVED")
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
