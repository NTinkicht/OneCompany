from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import bootstrap  # noqa: E402
import knowledge  # noqa: E402
from onecompany_lib import CONTROL  # noqa: E402


class KnowledgeTests(unittest.TestCase):
    def _candidate(self, entry_id: str = "K-TEST-CANDIDATE-001") -> dict:
        return {
            "schema": knowledge.ENTRY_SCHEMA,
            "id": entry_id,
            "title": "Candidate lesson",
            "status": "candidate",
            "authority": "advisory_only",
            "authority_effects": [],
            "category": "security",
            "summary": "A test candidate lesson.",
            "problem_pattern": "Mutable evidence is reused after state changes.",
            "failure_mode": "Stale evidence is trusted.",
            "root_cause": "Freshness was not reconciled.",
            "prevention_rule": "Reconcile authoritative state before consequential use.",
            "preflight_checks": ["reconcile live state"],
            "regression_tests": ["test stale evidence rejection"],
            "scope_tags": ["security", "authority"],
            "source_evidence": [
                {
                    "kind": "review_finding",
                    "ref": "https://github.com/NTinkicht/OneCompany/pull/55",
                    "actor": "reviewer-a",
                    "severity": "major",
                    "commit": "0" * 40,
                }
            ],
            "first_observed_at": "2026-09-16T00:00:00Z",
            "last_confirmed_at": "2026-09-16T00:00:00Z",
            "observed_count": 1,
            "confidence": "medium",
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

    def test_repo_store_validates_and_candidate_is_not_injected(self):
        entries = knowledge.load_entries()
        self.assertGreaterEqual(len(entries), 4)
        candidates = [item for item in entries if item["status"] == "candidate"]
        self.assertTrue(any(item["id"] == "K-OC-QUALIFICATION-TOCTOU-001" for item in candidates))
        retrieved = knowledge.retrieve_current(query="qualification hard link toctou")
        self.assertNotIn("K-OC-QUALIFICATION-TOCTOU-001", [item["id"] for item in retrieved])

    def test_retrieval_is_relevant_bounded_and_current_only(self):
        lessons = knowledge.retrieve_current(tags=["authority", "exact-head"], limit=99)
        self.assertLessEqual(len(lessons), 8)
        self.assertTrue(lessons)
        self.assertEqual(lessons[0]["id"], "K-GEN-EXACT-STATE-001")
        self.assertTrue(all(item["status"] == "current" for item in lessons))

    def test_preflight_is_advisory_and_cannot_create_gate(self):
        result = knowledge.preflight(tags=["filesystem", "security"], risk="security")
        self.assertEqual(result["authority"], "advisory_only")
        self.assertEqual(result["authority_effects"], [])
        self.assertFalse(result["hard_gate_created"])
        self.assertIn("K-GEN-RACE-BOUNDARY-001", result["lesson_ids"])
        self.assertTrue(result["checks"])
        self.assertTrue(result["regression_tests"])

    def test_duplicate_candidates_merge_without_losing_provenance(self):
        first = self._candidate("K-TEST-CANDIDATE-001")
        second = self._candidate("K-TEST-CANDIDATE-002")
        second["source_evidence"] = [
            {
                "kind": "ci_failure",
                "ref": "https://github.com/NTinkicht/OneCompany/actions/runs/123",
                "actor": "github-actions",
                "severity": "major",
                "commit": "1" * 40,
            }
        ]
        second["observed_count"] = 2
        merged = knowledge.deduplicate_candidates([first, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["observed_count"], 3)
        self.assertEqual(len(merged[0]["source_evidence"]), 2)

    def test_conflicting_claims_remain_separate(self):
        first = self._candidate("K-TEST-CANDIDATE-001")
        second = self._candidate("K-TEST-CANDIDATE-002")
        second["prevention_rule"] = "Never reconcile live state; trust cache permanently."
        conflicts = knowledge.detect_conflicts([first, second])
        self.assertEqual(conflicts, [{"left": "K-TEST-CANDIDATE-001", "right": "K-TEST-CANDIDATE-002"}])

    def test_untrusted_candidate_cannot_become_current_without_validation(self):
        candidate = self._candidate()
        candidate["status"] = "current"
        with self.assertRaisesRegex(knowledge.KnowledgeError, "current knowledge requires validation"):
            knowledge.validate_entry(candidate)

    def test_explicit_regression_evidence_can_promote_candidate_advisory_only(self):
        promoted = knowledge.promote_candidate(
            self._candidate(),
            method="regression_test",
            evidence_refs=["repo:.onecompany/selftest/test_knowledge.py"],
            validated_at="2026-09-16T01:00:00Z",
        )
        self.assertEqual(promoted["status"], "current")
        self.assertEqual(promoted["authority"], "advisory_only")
        self.assertEqual(promoted["authority_effects"], [])
        self.assertTrue(promoted["validation"]["validated"])

    def test_authority_smuggling_is_rejected(self):
        current = copy.deepcopy(
            next(item for item in knowledge.load_entries() if item["status"] == "current")
        )
        current["authority_effects"] = ["merge"]
        with self.assertRaisesRegex(knowledge.KnowledgeError, "advisory_only"):
            knowledge.validate_entry(current)

    def test_archived_lesson_is_excluded_from_normal_context(self):
        archived = knowledge.archive_entry(
            knowledge.promote_candidate(
                self._candidate(),
                method="regression_test",
                evidence_refs=["repo:.onecompany/selftest/test_knowledge.py"],
                validated_at="2026-09-16T01:00:00Z",
            ),
            reason="superseded by stronger rule",
        )
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(archived["authority_effects"], [])

    def test_fresh_bootstrap_scrubs_project_history_and_keeps_safe_generic_lessons(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            destination = target / ".onecompany" / "knowledge"
            shutil.copytree(CONTROL / "knowledge", destination)
            bootstrap.initialize_knowledge(target)
            self.assertEqual(list((destination / "candidate").glob("*.json")), [])
            self.assertEqual(list((destination / "archived").glob("*.json")), [])
            currents = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (destination / "current").glob("*.json")
            ]
            self.assertTrue(currents)
            self.assertTrue(all(item["bootstrap_safe"] is True for item in currents))
            self.assertTrue(all(item["authority"] == "advisory_only" for item in currents))


if __name__ == "__main__":
    unittest.main()
