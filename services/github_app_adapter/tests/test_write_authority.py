"""GitHub ledger provenance: fail closed on missing/edited/colliding leases."""
from __future__ import annotations
import datetime as dt
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from write_authority import active_implementation_lease, parse_trusted_events
from write_policy import WriteRefused

NOW = dt.datetime(2026, 9, 19, 12, 0, tzinfo=dt.timezone.utc)
def comment(body, id=1, user="NTinkicht", created="2026-09-19T11:00:00Z", updated=None):
    return {"id":id,"user":{"login":user},"created_at":created,
            "updated_at":created if updated is None else updated,"body":body}
def event(type="ROLE_LEASE_ASSIGNED",actor="grok-4-6-interactive",payload=None,event_id="evt1"):
    import json
    p = {"lease_id":"lease1", "pr":106, "work_unit":"WU-GROK",
         "branch":"wu-grok", "role":"implementation",
         "start_head":"a"*40}
    if payload: p.update(payload)
    obj={"version":2,"event_id":event_id,"type":type,"actor":actor,
         "timestamp":"2026-09-19T11:00:00Z","payload":p}
    return "<!-- onecompany-ledger-v1 -->\n```json\n"+json.dumps(obj)+"\n```"

class TrustedEventsTests(unittest.TestCase):
    def parse(self, xs):
        return parse_trusted_events(xs, {"NTinkicht"})

    def test_valid_unedited_publisher_only(self):
        e=self.parse([comment(event()),comment(event(event_id="ignored"),2,user="unknown")])
        self.assertEqual(len(e),1)
        self.assertEqual(e[0]["actor"],"grok-4-6-interactive")
        lease=active_implementation_lease(e,lease_id="lease1",
             work_unit="WU-GROK",pr_number=106,now=NOW,ttl_seconds=14400)
        self.assertEqual(lease["status"],"active")

    def test_expired_duplicate_edited_and_released_are_denied(self):
        with self.assertRaisesRegex(WriteRefused,"edited"):
            self.parse([comment(event(),updated="2026-09-19T11:00:01Z")])
        with self.assertRaisesRegex(WriteRefused,"duplicate"):
            self.parse([comment(event()),comment(event(),2)])
        e=self.parse([comment(event())])
        with self.assertRaisesRegex(WriteRefused,"expired"):
            active_implementation_lease(e,lease_id="lease1",
                work_unit="WU-GROK",pr_number=106,
                now=NOW+dt.timedelta(hours=4),ttl_seconds=14400)
        released=self.parse([comment(event()),
                            comment(event(type="ROLE_LEASE_RELEASED",
                                payload={"lease_id":"lease1"},event_id="evt2"),2)])
        with self.assertRaisesRegex(WriteRefused,"not_unique"):
            active_implementation_lease(released,lease_id="lease1",
                work_unit="WU-GROK",pr_number=106,now=NOW,ttl_seconds=14400)

    def test_later_unverifiable_renewal_never_extends_authority(self):
        e=self.parse([comment(event()), comment(event(
            type="ROLE_LEASE_RENEWED",event_id="evt2"),2)])
        with self.assertRaisesRegex(WriteRefused,"renewal_requires"):
            active_implementation_lease(e,lease_id="lease1",
                work_unit="WU-GROK",pr_number=106,now=NOW,ttl_seconds=14400)

if __name__ == "__main__":
    unittest.main()
