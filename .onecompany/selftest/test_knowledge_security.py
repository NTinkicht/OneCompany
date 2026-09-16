from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import bootstrap  # noqa: E402
import knowledge  # noqa: E402
import qualification  # noqa: E402
from onecompany_lib import CONTROL  # noqa: E402


class KnowledgeSecurityTests(unittest.TestCase):
    def _candidate(self, entry_id: str = "K-SEC-TEST-001") -> dict:
        return {
            "schema": knowledge.ENTRY_SCHEMA,
            "id": entry_id,
            "title": "Security test lesson",
            "status": "candidate",
            "authority": "advisory_only",
            "authority_effects": [],
            "category": "security",
            "summary": "A deterministic test lesson.",
            "problem_pattern": "Mutable state changes between validation and use.",
            "failure_mode": "The wrong state is used.",
            "root_cause": "Identity was not bound across the operation.",
            "prevention_rule": "Bind validation and mutation to stable identity.",
            "preflight_checks": ["challenge mutable identity"],
            "regression_tests": ["test stable identity"],
            "scope_tags": ["security", "knowledge"],
            "source_evidence": [
                {
                    "kind": "repository_policy",
                    "ref": "repo:docs/LEARNING-PLANE.md",
                    "actor": "onecompany",
                    "severity": "high",
                    "commit": None,
                }
            ],
            "first_observed_at": "2026-09-16T00:00:00Z",
            "last_confirmed_at": "2026-09-16T00:00:00Z",
            "observed_count": 1,
            "confidence": "high",
            "supersedes": [],
            "superseded_by": [],
            "applicability_notes": "Test only.",
            "bootstrap_safe": False,
            "validation": {
                "validated": False,
                "method": None,
                "evidence_refs": [],
                "validated_at": None,
            },
        }

    def _copy_manifest(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CONTROL / "knowledge" / "manifest.json", root / "manifest.json")
        for state in knowledge.STATES:
            (root / state).mkdir(exist_ok=True)

    def test_manifest_rejects_sensitive_and_unsupported_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_manifest(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["credential"] = "do-not-store"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises((knowledge.KnowledgeError, qualification.QualificationInputError)):
                knowledge.load_manifest(root)

    def test_secure_entry_write_cannot_follow_final_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "current"
            state.mkdir(parents=True)
            protected = root / "protected.txt"
            protected.write_text("protected\n", encoding="utf-8")
            target = state / "K-SEC-TEST-001.json"
            target.symlink_to(protected)
            with self.assertRaises(knowledge.KnowledgeError):
                knowledge._write_entry(target, {"safe": True})
            self.assertEqual(protected.read_text(encoding="utf-8"), "protected\n")

    def test_transition_cleanup_failure_rolls_back_to_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_manifest(root)
            source = root / "candidate" / "K-SEC-TEST-001.json"
            destination = root / "current" / "K-SEC-TEST-001.json"
            candidate = self._candidate()
            current = knowledge.promote_candidate(
                candidate,
                method="regression_test",
                evidence_refs=["repo:.onecompany/selftest/test_knowledge_security.py"],
                validated_at="2026-09-16T01:00:00Z",
            )
            knowledge._write_entry(source, candidate)
            real_unlink = knowledge._safe_unlink
            failed = False

            def fail_next_once(path: Path) -> None:
                nonlocal failed
                if not failed and path.name.endswith(".next.json"):
                    failed = True
                    raise knowledge.KnowledgeError("simulated cleanup failure")
                real_unlink(path)

            with patch.object(knowledge, "_safe_unlink", side_effect=fail_next_once):
                with self.assertRaisesRegex(knowledge.KnowledgeError, "cleanup failed"):
                    knowledge._transition_entry(source, destination, current, root)

            self.assertTrue(failed)
            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())
            tx_root = root / ".transactions"
            self.assertFalse(any(tx_root.glob("*.json")))

    def test_interrupted_transition_is_recovered_without_duplicate_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_manifest(root)
            entry_id = "K-SEC-TEST-001"
            source = root / "candidate" / f"{entry_id}.json"
            destination = root / "current" / f"{entry_id}.json"
            candidate = self._candidate(entry_id)
            current = knowledge.promote_candidate(
                candidate,
                method="regression_test",
                evidence_refs=["repo:.onecompany/selftest/test_knowledge_security.py"],
                validated_at="2026-09-16T01:00:00Z",
            )
            knowledge._write_entry(source, candidate)
            tx_root = root / ".transactions"
            tx_root.mkdir()
            prefix = f"{entry_id}--candidate--current"
            next_path = tx_root / f"{prefix}.next.json"
            staged = tx_root / f"{prefix}.source.json"
            knowledge._write_entry(next_path, current)
            knowledge._replace_between(source, staged)

            entries = knowledge.load_entries(root)
            self.assertEqual([item["id"] for item in entries], [entry_id])
            self.assertEqual(entries[0]["status"], "current")
            self.assertFalse(source.exists())
            self.assertTrue(destination.exists())
            self.assertFalse(any(tx_root.glob("*.json")))

    def test_bootstrap_rejects_project_actor_identity_in_safe_lesson(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            destination = target / ".onecompany" / "knowledge"
            shutil.copytree(CONTROL / "knowledge", destination)
            current = next((destination / "current").glob("*.json"))
            entry = json.loads(current.read_text(encoding="utf-8"))
            entry["source_evidence"][0]["actor"] = "project-reviewer"
            current.write_text(json.dumps(entry), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reviewer identity"):
                bootstrap.initialize_knowledge(target)

    def test_bootstrap_rejects_project_commit_and_validation_url(self):
        for mutation, expected in (
            ("commit", "commit identity"),
            ("validation", "validation evidence"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                destination = target / ".onecompany" / "knowledge"
                shutil.copytree(CONTROL / "knowledge", destination)
                current = next((destination / "current").glob("*.json"))
                entry = json.loads(current.read_text(encoding="utf-8"))
                if mutation == "commit":
                    entry["source_evidence"][0]["commit"] = "a" * 40
                else:
                    entry["validation"]["evidence_refs"] = [
                        "https://github.com/NTinkicht/OneCompany/actions/runs/1"
                    ]
                current.write_text(json.dumps(entry), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, expected):
                    bootstrap.initialize_knowledge(target)

    def test_archived_entry_is_absent_from_normal_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_manifest(root)
            archived = knowledge.archive_entry(
                self._candidate(),
                reason="superseded by stronger rule",
            )
            knowledge._write_entry(root / "archived" / f"{archived['id']}.json", archived)
            retrieved = knowledge.retrieve_current(query="mutable state", root=root)
            self.assertNotIn(archived["id"], {item["id"] for item in retrieved})


if __name__ == "__main__":
    unittest.main()
