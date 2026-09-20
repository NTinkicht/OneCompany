from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from schema_validate import validate

CONTROL = ROOT / ".onecompany"
SCHEMA = json.loads(
    (CONTROL / "schemas" / "external-capability-register.schema.json").read_text(encoding="utf-8")
)
REGISTER = json.loads(
    (CONTROL / "external-capability-register.json").read_text(encoding="utf-8")
)


class ExternalCapabilityRegisterTests(unittest.TestCase):
    def check(self, document):
        errors = []
        validate(document, SCHEMA, "external-capability-register.json", errors)
        return errors

    def test_full_inventory_is_valid(self):
        self.assertEqual([], self.check(REGISTER))

    def test_duplicate_id_even_if_metadata_differs_is_rejected(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][1]["capability_id"] = changed["candidates"][0]["capability_id"]
        errors = self.check(changed)
        self.assertTrue(any("duplicate" in e and "capability_id" in e for e in errors), errors)
        self.assertTrue(any("missing required capability_id" in e for e in errors), errors)

    def test_duplicate_repository_even_if_id_differs_is_rejected(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][1]["repository_or_project"] = changed["candidates"][0]["repository_or_project"]
        errors = self.check(changed)
        self.assertTrue(any("duplicate" in e and "repository_or_project" in e for e in errors), errors)
        self.assertTrue(any("missing required repository_or_project" in e for e in errors), errors)

    def test_duplicate_assessment_task_is_rejected(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][1]["candidate_assessment_task"] = changed["candidates"][0]["candidate_assessment_task"]
        errors = self.check(changed)
        self.assertTrue(any("duplicate" in e and "candidate_assessment_task" in e for e in errors), errors)

    def test_missing_candidate_cannot_pass_with_correct_length(self):
        changed = copy.deepcopy(REGISTER)
        changed["candidates"][-1] = copy.deepcopy(changed["candidates"][0])
        errors = self.check(changed)
        self.assertTrue(any("missing required capability_id" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
