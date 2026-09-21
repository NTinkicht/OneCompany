"""Observed Grok scheduled reader must not accidentally qualify writer/reviewer roles."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(name: str) -> dict:
    return json.loads((ROOT / ".onecompany" / name).read_text(encoding="utf-8"))


class GrokScheduledReaderTests(unittest.TestCase):
    def test_scheduled_provider_reader_is_only_verified_unattended_route(self):
        actors = read("actors.json")
        readiness = read("readiness.json")
        dispatch = read("dispatch.json")
        actor = next(x for x in actors["actors"]
                     if x["id"] == "grok-4-6-interactive")
        record = next(x for x in readiness["actors"]
                      if x["actor_id"] == actor["id"])
        mechanisms = next(x for x in dispatch["actors"]
                          if x["actor_id"] == actor["id"])["mechanisms"]
        scheduled = next(x for x in mechanisms
                         if x["id"] == "grok-supergrok-scheduled-readonly")
        event = next(x for x in mechanisms
                     if x["id"] == "grok-supergrok-cloud-wake")
        self.assertTrue(scheduled["configured"])
        self.assertTrue(scheduled["unattended"])
        self.assertEqual(scheduled["kind"], "scheduled_task")
        self.assertEqual(scheduled["capabilities"], ["repository_intelligence"])
        self.assertFalse(event["configured"])
        self.assertEqual(event["capabilities"], [])
        self.assertTrue(record["unattended"]["configured"])
        self.assertTrue(record["unattended"]["verified"])
        self.assertEqual(record["verified_capabilities"],
                         ["repository_intelligence"])
        self.assertTrue(record["repository_access"]["read"])
        for prohibited in ("write", "review", "merge"):
            self.assertFalse(record["repository_access"][prohibited])
        self.assertEqual(record["capacity"]["implementation_streams"], 0)
        self.assertEqual(actor["permissions"], ["read"])
        self.assertFalse(actor["may_independently_gate_own_material_authorship"])
        self.assertIn("5758144418", " ".join(record["evidence"]))
        self.assertIn("6936b331", " ".join(scheduled["evidence"]))

    def test_only_repository_intelligence_is_dispatchable_via_scheduled_bot(self):
        dispatch = read("dispatch.json")
        grok = next(x for x in dispatch["actors"]
                    if x["actor_id"] == "grok-4-6-interactive")
        for route in grok["mechanisms"]:
            if route["configured"]:
                self.assertEqual(route["capabilities"],
                                 ["repository_intelligence"])
        self.assertFalse(any(route["configured"] and
                             "code_review" in route["capabilities"]
                             for route in grok["mechanisms"]))


if __name__ == "__main__":
    unittest.main()
