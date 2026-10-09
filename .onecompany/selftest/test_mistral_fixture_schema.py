"""Verify the Mistral frozen fixture's local schema and canonical queue linkage."""
import json
import unittest
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


class MistralFixtureSchemaTests(unittest.TestCase):
    def test_schema_resolves_locally_and_preserves_canonical_work_units(self):
        fixture = json.loads((FIXTURES / "mistral_queue_v1.json").read_text())
        relative_schema = fixture["$schema"]
        self.assertEqual(relative_schema, "./mistral_queue_v1.schema.json")
        schema_path = (FIXTURES / relative_schema).resolve(strict=True)
        self.assertEqual(schema_path.parent, FIXTURES.resolve())
        schema = json.loads(schema_path.read_text())
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(fixture), set(schema["required"]) | {"$schema"})
        self.assertEqual(set(schema["required"]) - set(fixture), set())
        canonical_path = (
            schema_path.parent / schema["properties"]["work_units"]["$ref"].split("#")[0]
        ).resolve(strict=True)
        self.assertEqual(canonical_path, ROOT / ".onecompany/schemas/queue.schema.json")
        canonical = json.loads(canonical_path.read_text())
        self.assertEqual(
            schema["properties"]["work_units"]["$ref"].split("#")[1],
            "/properties/work_units",
        )
        units = fixture["work_units"]
        self.assertIsInstance(units, list)
        self.assertTrue(units)
        item_schema = canonical["properties"]["work_units"]["items"]
        for unit in units:
            self.assertTrue(set(item_schema["required"]).issubset(unit))
            self.assertIn(unit["status"], item_schema["properties"]["status"]["enum"])
        self.assertTrue(fixture["project"]["repository"].startswith("example/"))
        self.assertEqual(fixture["snapshot"]["source"], "fixture-mistral-queue-v1")
        self.assertIn("Synthetic", fixture["fixture_note"])


if __name__ == "__main__":
    unittest.main()
