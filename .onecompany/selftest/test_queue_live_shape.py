"""Live planning-schema smoke test, intentionally separate from Mistral fixtures."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LiveQueueShapeTests(unittest.TestCase):
    def test_live_queue_structural_contract(self):
        """Verify live shape, not current WU readiness, IDs or PR numbers."""
        schema = json.loads((ROOT / ".onecompany/schemas/queue.schema.json").read_text())
        queue = json.loads((ROOT / ".onecompany/queue.json").read_text())
        self.assertTrue(set(schema["required"]).issubset(queue))
        self.assertIsInstance(queue["schema_version"], str)
        self.assertIsInstance(queue["work_units"], list)
        item_schema = schema["properties"]["work_units"]["items"]
        required = set(item_schema["required"])
        allowed_states = set(item_schema["properties"]["status"]["enum"])
        seen = set()
        for unit in queue["work_units"]:
            self.assertIsInstance(unit, dict)
            self.assertTrue(required.issubset(unit))
            self.assertRegex(unit["id"], r"^WU[0-9A-Za-z._-]+$")
            self.assertNotIn(unit["id"], seen)
            seen.add(unit["id"])
            self.assertIn(unit["status"], allowed_states)
            self.assertIsInstance(unit["dependencies"], list)
            self.assertEqual(len(unit["dependencies"]),
                             len(set(unit["dependencies"])))
            self.assertIs(type(unit["priority"]), int)


if __name__ == "__main__":
    unittest.main()
