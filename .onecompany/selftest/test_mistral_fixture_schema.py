"""Validate the entire synthetic Mistral queue fixture against its local schema.

Resolve only the two vetted relative references into the canonical queue
schema, then reuse OneCompany's production dependency-free schema validator.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / ".onecompany/selftest/fixtures"
sys.path.insert(0, str(ROOT / "scripts"))
from schema_validate import validate  # noqa: E402


def resolved_fixture_schema() -> dict:
    fixture_path = FIXTURES / "mistral_queue_v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["$schema"] == "../mistral_queue_v1.schema.json"
    schema_file = (FIXTURES / fixture["$schema"]).resolve(strict=True)
    assert schema_file == ROOT / ".onecompany/selftest/mistral_queue_v1.schema.json"
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    canonical_file = ROOT / ".onecompany/schemas/queue.schema.json"

    def expand(value, current_file):
        if isinstance(value, list):
            return [expand(item, current_file) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            if set(value) != {"$ref"}:
                raise AssertionError("Fixture schema reference has unsupported siblings")
            relpath, sep, pointer = value["$ref"].partition("#")
            target = (current_file.parent / relpath).resolve(strict=True)
            if not sep or target != canonical_file or pointer not in (
                "/properties/work_units", "/properties/schema_version"
            ):
                raise AssertionError("Unapproved local fixture schema reference")
            selected = json.loads(target.read_text(encoding="utf-8"))
            for part in pointer.split("/")[1:]:
                selected = selected[part.replace("~1", "/").replace("~0", "~")]
            return expand(selected, target)
        return {name: expand(child, current_file) for name, child in value.items()}

    return expand(schema, schema_file)


class MistralFixtureSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = resolved_fixture_schema()
        cls.fixture = json.loads(
            (FIXTURES / "mistral_queue_v1.json").read_text(encoding="utf-8")
        )

    def validate_fixture(self, fixture):
        errors = []
        validate(fixture, self.schema, "mistral_queue_fixture", errors)
        return errors

    def test_complete_fixture_schema_passes(self):
        self.assertFalse(self.validate_fixture(self.fixture))

    def test_wrong_priority_type_is_rejected(self):
        altered = copy.deepcopy(self.fixture)
        altered["work_units"][0]["priority"] = "HIGH"
        errors = self.validate_fixture(altered)
        self.assertTrue(any("priority" in error and "integer" in error
                            for error in errors), errors)

    def test_duplicate_dependencies_are_rejected(self):
        altered = copy.deepcopy(self.fixture)
        altered["work_units"][0]["dependencies"] = ["WU-PFC-001", "WU-PFC-001"]
        errors = self.validate_fixture(altered)
        self.assertTrue(any("dependencies" in error and "unique" in error
                            for error in errors), errors)

    def test_nested_priority_policy_is_rejected(self):
        altered = copy.deepcopy(self.fixture)
        altered["work_units"][0]["priority_inputs"]["confidence"] = 2.0
        errors = self.validate_fixture(altered)
        self.assertTrue(any("confidence" in error and "maximum" in error
                            for error in errors), errors)

    def test_unapproved_fixture_repository_is_rejected(self):
        altered = copy.deepcopy(self.fixture)
        altered["project"]["repository"] = "NTinkicht/OneCompany"
        errors = self.validate_fixture(altered)
        self.assertTrue(any("project.repository" in error and "pattern" in error
                            for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
